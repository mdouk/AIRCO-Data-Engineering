"""Export Sage 100 business entities + their relationships into ONE SQLite file.

Produces a single, portable output/sage_extract.sqlite containing:
  - one table per selected entity (articles/materials, products, suppliers,
    customers, BOM, prices, product groups, ...), records only
  - _relationships : parent_table.column -> ref_table.column, marked 'declared'
    (real FK in the source) or 'inferred' (matched by shared key column)
  - _tables        : every exported table with its row count
  - _columns       : column layout of every exported table
  - indexes on all relationship key columns (fast local joins)

Source is chosen in config.SOURCE ('local' Docker restore, or 'remote' read-only
login). Table/FK names are discovered from the live catalog — nothing is hard-coded
to a specific Sage version.

Usage:
    python src/export_to_sqlite.py                 # uses config.MANDANT_DB
    python src/export_to_sqlite.py --db OL_AIRCO
    python src/export_to_sqlite.py --db OL_AIRCO --selection all
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

import pandas as pd
from sqlalchemy import text

import config
from db import get_engine

CHUNK = 50_000  # rows per batch when copying large tables


# --------------------------------------------------------------------------- #
# Catalog reads (MS SQL Server system views)
# --------------------------------------------------------------------------- #
def read_tables(engine) -> pd.DataFrame:
    q = text(
        """
        SELECT s.name AS [schema], t.name AS [table], t.object_id AS object_id
        FROM sys.tables t
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        ORDER BY s.name, t.name
        """
    )
    with engine.connect() as c:
        return pd.read_sql(q, c)


def read_rowcounts(engine) -> dict[int, int]:
    # sys.partitions is a catalog view -> readable by db_datareader (no DMV perms).
    q = text(
        """
        SELECT p.object_id, SUM(p.rows) AS rows
        FROM sys.partitions p
        WHERE p.index_id IN (0, 1)
        GROUP BY p.object_id
        """
    )
    with engine.connect() as c:
        df = pd.read_sql(q, c)
    return {int(r.object_id): int(r.rows) for r in df.itertuples()}


def read_declared_fks(engine) -> pd.DataFrame:
    q = text(
        """
        SELECT fk.name AS fk_name,
               sp.name AS parent_schema, tp.name AS parent_table, cp.name AS parent_column,
               sr.name AS ref_schema,    tr.name AS ref_table,    cr.name AS ref_column
        FROM sys.foreign_keys fk
        JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
        JOIN sys.tables  tp ON tp.object_id = fkc.parent_object_id
        JOIN sys.schemas sp ON sp.schema_id = tp.schema_id
        JOIN sys.columns cp ON cp.object_id = fkc.parent_object_id AND cp.column_id = fkc.parent_column_id
        JOIN sys.tables  tr ON tr.object_id = fkc.referenced_object_id
        JOIN sys.schemas sr ON sr.schema_id = tr.schema_id
        JOIN sys.columns cr ON cr.object_id = fkc.referenced_object_id AND cr.column_id = fkc.referenced_column_id
        ORDER BY fk.name, fkc.constraint_column_id
        """
    )
    with engine.connect() as c:
        return pd.read_sql(q, c)


def read_key_columns(engine) -> pd.DataFrame:
    """Columns that are a primary key or part of a unique index (inference targets)."""
    q = text(
        """
        SELECT s.name AS [schema], t.name AS [table], c.name AS [column],
               MAX(CAST(i.is_primary_key AS int)) AS is_pk
        FROM sys.indexes i
        JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
        JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
        JOIN sys.tables  t ON t.object_id = i.object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        WHERE i.is_primary_key = 1 OR i.is_unique = 1
        GROUP BY s.name, t.name, c.name
        """
    )
    with engine.connect() as c:
        return pd.read_sql(q, c)


def read_columns(engine, schema: str, table: str) -> pd.DataFrame:
    q = text(
        """
        SELECT COLUMN_NAME AS column_name, DATA_TYPE AS data_type,
               CHARACTER_MAXIMUM_LENGTH AS max_len, IS_NULLABLE AS nullable
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = :s AND TABLE_NAME = :t
        ORDER BY ORDINAL_POSITION
        """
    )
    with engine.connect() as c:
        return pd.read_sql(q, c, params={"s": schema, "t": table})


# Column types that crash pymssql mid-stream or aren't needed for entities/relationships.
_LOB_BINARY = {"image", "binary", "varbinary", "timestamp", "rowversion",
               "geography", "geometry", "hierarchyid"}
_LOB_TEXT = {"text", "ntext", "xml", "sql_variant"}


def build_select(schema: str, table: str, cols: pd.DataFrame) -> str:
    """SELECT that neutralises problem columns: binary/LOB -> NULL, text/xml/variant
    -> nvarchar(max). Everything else stays as-is. Avoids pymssql error 20047."""
    parts = []
    for cn, dt in zip(cols["column_name"], cols["data_type"]):
        d = str(dt).lower()
        if d in _LOB_BINARY:
            parts.append(f"CAST(NULL AS int) AS [{cn}]")
        elif d in _LOB_TEXT:
            parts.append(f"CAST([{cn}] AS nvarchar(max)) AS [{cn}]")
        elif d == "bit":
            # Genuine bit columns -> clean 1/0 (rare here; Sage's Ist*/Hat* flags are
            # int -1/0 and pass through as-is, preserving the faithful source value).
            parts.append(f"CASE WHEN [{cn}] <> 0 THEN 1 ELSE 0 END AS [{cn}]")
        else:
            parts.append(f"[{cn}]")
    return f"SELECT {', '.join(parts)} FROM [{schema}].[{table}]"


# --------------------------------------------------------------------------- #
# Table selection
# --------------------------------------------------------------------------- #
def select_tables(tables: pd.DataFrame, fks: pd.DataFrame, mode: str) -> pd.DataFrame:
    names = tables["table"].str.lower()
    if mode == "all":
        return tables
    if mode == "khk":
        return tables[names.str.contains("khk")]

    # mode == "entities": keyword seeds + declared-FK closure
    seed_mask = names.apply(lambda n: any(k in n for k in config.ENTITY_KEYWORDS))
    selected = set(tables[seed_mask]["table"].str.lower())

    if not fks.empty:
        changed = True
        while changed:
            changed = False
            for r in fks.itertuples():
                p, rf = r.parent_table.lower(), r.ref_table.lower()
                if p in selected and rf not in selected:
                    selected.add(rf); changed = True
                if rf in selected and p not in selected:
                    selected.add(p); changed = True

    # Curate: drop transactional/history/system tables even if keyword-matched.
    subs = config.EXCLUDE_SUBSTRINGS
    pref = tuple(config.EXCLUDE_PREFIXES)
    selected = {n for n in selected
               if not (any(s in n for s in subs) or n.startswith(pref))}

    # Always include explicitly-listed extras that exist in the DB.
    selected |= {t.lower() for t in config.EXTRA_TABLES} & set(names)

    return tables[names.isin(selected)]


# --------------------------------------------------------------------------- #
# Relationship inference (for schemas with no declared FKs)
# --------------------------------------------------------------------------- #
def infer_relationships(engine, selected: pd.DataFrame, keys: pd.DataFrame) -> pd.DataFrame:
    """Match a column in table A to a PK/unique column of the same name in table B."""
    sel_names = set(selected["table"])
    # Candidate reference columns: PK/unique columns in selected tables, non-generic.
    key_targets: dict[str, list[tuple[str, str]]] = {}
    for r in keys.itertuples():
        if r.table not in sel_names:
            continue
        col = r.column
        if col.lower() in config.INFERENCE_STOPLIST or len(col) < 4:
            continue
        key_targets.setdefault(col.lower(), []).append((r.table, col))

    rows = []
    for r in selected.itertuples():
        cols = read_columns(engine, r.schema, getattr(r, "table"))
        for col in cols["column_name"]:
            lc = col.lower()
            if lc in config.INFERENCE_STOPLIST or lc not in key_targets:
                continue
            for ref_table, ref_col in key_targets[lc]:
                if ref_table == getattr(r, "table"):
                    continue  # not a self key
                rows.append({
                    "parent_table": getattr(r, "table"), "parent_column": col,
                    "ref_table": ref_table, "ref_column": ref_col,
                    "kind": "inferred",
                })
    return pd.DataFrame(rows).drop_duplicates() if rows else pd.DataFrame(
        columns=["parent_table", "parent_column", "ref_table", "ref_column", "kind"]
    )


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="Source database (default: config.MANDANT_DB)")
    ap.add_argument("--selection", choices=["entities", "khk", "all"],
                    default=config.TABLE_SELECTION)
    ap.add_argument("--out", default=config.SQLITE_OUT)
    args = ap.parse_args()

    db = args.db or config.MANDANT_DB
    if not db:
        sys.exit("No source database. Set MANDANT_DB in config.py or pass --db.")

    engine = get_engine(db)
    print(f"Source: {config.SOURCE} / database '{db}'")

    tables = read_tables(engine)
    fks = read_declared_fks(engine)
    keys = read_key_columns(engine)
    counts = read_rowcounts(engine)
    print(f"  {len(tables)} tables, {len(fks)} declared FK columns in source.")

    selected = select_tables(tables, fks, args.selection).reset_index(drop=True)
    print(f"  selection='{args.selection}' -> {len(selected)} tables to export.")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    if os.path.exists(args.out):
        os.remove(args.out)
    sqlite_conn = sqlite3.connect(args.out)

    # ---- copy table data ----
    table_meta, col_meta, failures = [], [], []
    for r in selected.itertuples():
        schema, table = r.schema, getattr(r, "table")
        n = counts.get(int(r.object_id), None)
        print(f"    {schema}.{table} ({n if n is not None else '?'} rows)")
        cols = read_columns(engine, schema, table)
        select_sql = build_select(schema, table, cols)
        first, total = True, 0
        try:
            with engine.connect() as c:   # no server-side cursor; pymssql buffers
                for chunk in pd.read_sql(text(select_sql), c, chunksize=CHUNK):
                    chunk.to_sql(table, sqlite_conn,
                                 if_exists="replace" if first else "append", index=False)
                    first, total = False, total + len(chunk)
            if first:  # empty table -> create with correct columns
                pd.read_sql(text(select_sql + " WHERE 1=0"), engine).to_sql(
                    table, sqlite_conn, if_exists="replace", index=False)
        except Exception as e:  # noqa: BLE001 — isolate one bad table, keep going
            print(f"      ! FAILED {schema}.{table}: {str(e)[:160]}")
            sqlite_conn.execute(f'DROP TABLE IF EXISTS "{table}"')
            failures.append(table)
            continue
        table_meta.append({"table": table, "schema": schema, "rows": total})
        cols.insert(0, "table", table)
        col_meta.append(cols)

    # ---- relationships (declared + inferred) ----
    rel_parts = []
    if not fks.empty:
        d = fks[["parent_table", "parent_column", "ref_table", "ref_column"]].copy()
        d["kind"] = "declared"
        rel_parts.append(d)
    if config.INFER_RELATIONSHIPS:
        inf = infer_relationships(engine, selected, keys)
        if not inf.empty:
            rel_parts.append(inf)
    relationships = (pd.concat(rel_parts, ignore_index=True).drop_duplicates()
                     if rel_parts else pd.DataFrame(
                         columns=["parent_table", "parent_column",
                                  "ref_table", "ref_column", "kind"]))

    # ---- metadata tables ----
    pd.DataFrame(table_meta).to_sql("_tables", sqlite_conn, if_exists="replace", index=False)
    (pd.concat(col_meta, ignore_index=True) if col_meta else pd.DataFrame()) \
        .to_sql("_columns", sqlite_conn, if_exists="replace", index=False)
    relationships.to_sql("_relationships", sqlite_conn, if_exists="replace", index=False)

    # ---- indexes on relationship key columns (fast joins) ----
    exported = {m["table"] for m in table_meta}
    cur = sqlite_conn.cursor()
    made = set()
    for r in relationships.itertuples():
        for tbl, col in ((r.parent_table, r.parent_column), (r.ref_table, r.ref_column)):
            if tbl in exported and (tbl, col) not in made:
                try:
                    cur.execute(f'CREATE INDEX IF NOT EXISTS '
                                f'"ix_{tbl}_{col}" ON "{tbl}" ("{col}")')
                    made.add((tbl, col))
                except sqlite3.OperationalError:
                    pass
    sqlite_conn.commit()
    sqlite_conn.close()

    n_decl = int((relationships["kind"] == "declared").sum()) if not relationships.empty else 0
    n_inf = int((relationships["kind"] == "inferred").sum()) if not relationships.empty else 0
    size_mb = os.path.getsize(args.out) / 1e6
    print(f"\nWrote {args.out}  ({size_mb:.1f} MB)")
    print(f"  tables exported : {len(table_meta)}")
    print(f"  relationships   : {n_decl} declared, {n_inf} inferred")
    print(f"  indexes created : {len(made)}")
    if failures:
        print(f"  !! skipped {len(failures)} table(s): {', '.join(failures)}")


if __name__ == "__main__":
    main()
