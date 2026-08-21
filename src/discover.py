"""Schema discovery for the restored Sage 100 database(s).

Writes output/schema_report.xlsx with:
  - Databases        : all user databases on the container
  - Tables           : every table + row count for each user DB
  - RelevantTables   : tables whose name matches DISCOVERY_KEYWORDS (article/BOM/price/...)
  - Columns_<table>  : column layout for the expected/relevant article tables

Run after restore.py. Use the report to confirm the Mandant DB and the real
table/column names, then set them in config.py.
"""
from __future__ import annotations

import os

import pandas as pd
from sqlalchemy import text

import config
from db import get_engine

SYSTEM_DBS = {"master", "tempdb", "model", "msdb"}


def list_user_databases(engine) -> list[str]:
    q = text("SELECT name FROM sys.databases WHERE database_id > 4 ORDER BY name")
    with engine.connect() as c:
        return [r[0] for r in c.execute(q)]


def tables_with_counts(db: str) -> pd.DataFrame:
    """Table list + approximate row counts (from sys.dm_db_partition_stats — fast)."""
    engine = get_engine(db)
    q = text(
        """
        SELECT s.name AS [schema], t.name AS [table],
               SUM(CASE WHEN p.index_id IN (0,1) THEN p.row_count ELSE 0 END) AS row_count
        FROM sys.tables t
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        JOIN sys.dm_db_partition_stats p ON p.object_id = t.object_id
        GROUP BY s.name, t.name
        ORDER BY row_count DESC
        """
    )
    with engine.connect() as c:
        df = pd.read_sql(q, c)
    df.insert(0, "database", db)
    return df


def columns_for(db: str, table: str) -> pd.DataFrame:
    engine = get_engine(db)
    q = text(
        """
        SELECT c.ORDINAL_POSITION AS pos, c.COLUMN_NAME AS column_name,
               c.DATA_TYPE AS data_type, c.CHARACTER_MAXIMUM_LENGTH AS max_len,
               c.IS_NULLABLE AS nullable
        FROM INFORMATION_SCHEMA.COLUMNS c
        WHERE c.TABLE_NAME = :t
        ORDER BY c.ORDINAL_POSITION
        """
    )
    with engine.connect() as c:
        return pd.read_sql(q, c, params={"t": table})


def main() -> None:
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(config.OUTPUT_DIR, "schema_report.xlsx")

    dbs = list_user_databases(get_engine(config.SYSTEM_DB))
    print("User databases:", dbs or "(none — did the restore succeed?)")

    all_tables = []
    for db in dbs:
        try:
            all_tables.append(tables_with_counts(db))
        except Exception as e:  # noqa: BLE001
            print(f"  ! could not inventory {db}: {e}")
    tables_df = pd.concat(all_tables, ignore_index=True) if all_tables else pd.DataFrame()

    # Relevant tables by keyword.
    if not tables_df.empty:
        mask = tables_df["table"].str.lower().apply(
            lambda n: any(k in n for k in config.DISCOVERY_KEYWORDS)
        )
        relevant = tables_df[mask].copy()
    else:
        relevant = pd.DataFrame()

    with pd.ExcelWriter(out_path, engine="xlsxwriter") as xw:
        pd.DataFrame({"database": dbs}).to_excel(xw, sheet_name="Databases", index=False)
        tables_df.to_excel(xw, sheet_name="Tables", index=False)
        relevant.to_excel(xw, sheet_name="RelevantTables", index=False)

        # Column layouts for the tables we most likely need.
        seen = set()
        targets = list(config.EXPECTED_ARTICLE_TABLES)
        if not relevant.empty:
            targets += relevant["table"].tolist()
        for _, row in (relevant.iterrows() if not relevant.empty else []):
            pass
        for db in dbs:
            db_tables = set(
                tables_df[tables_df["database"] == db]["table"].tolist()
            ) if not tables_df.empty else set()
            for t in targets:
                if t in db_tables and (db, t) not in seen:
                    seen.add((db, t))
                    sheet = f"Col_{t}"[:31]
                    try:
                        columns_for(db, t).to_excel(xw, sheet_name=sheet, index=False)
                    except Exception as e:  # noqa: BLE001
                        print(f"  ! columns for {db}.{t}: {e}")

    print(f"\nWrote {out_path}")
    print("Review it, then set MANDANT_DB and confirm table names in src/config.py.")


if __name__ == "__main__":
    main()
