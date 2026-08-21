"""Rebuild output/sage_extract.sqlite with real FOREIGN KEY constraints.

SQLite can't ALTER TABLE ADD a foreign key, so for each table we recreate it with the
FK clauses baked into the CREATE TABLE and copy the data across (all inside SQLite — no
re-query of table data). We use the *declared* FKs from the live catalog (grouped into
proper composite constraints), restricted to tables that exist in the export.

Result: DBeaver draws an ER diagram and Datasette renders foreign keys as clickable
links. FK enforcement stays OFF (the extract may contain values that don't satisfy every
constraint), but the schema metadata is what the tools read to visualise relationships.

    python src/add_foreign_keys.py
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict

import pandas as pd
from sqlalchemy import text

import config
from db import get_engine

META = {"_relationships", "_tables", "_columns"}


def grouped_declared_fks(engine) -> list[dict]:
    q = text(
        """
        SELECT fk.name AS fk, tp.name AS ptab, cp.name AS pcol,
               tr.name AS rtab, cr.name AS rcol, fkc.constraint_column_id AS ord
        FROM sys.foreign_keys fk
        JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
        JOIN sys.tables tp ON tp.object_id = fkc.parent_object_id
        JOIN sys.schemas sp ON sp.schema_id = tp.schema_id
        JOIN sys.columns cp ON cp.object_id = fkc.parent_object_id AND cp.column_id = fkc.parent_column_id
        JOIN sys.tables tr ON tr.object_id = fkc.referenced_object_id
        JOIN sys.schemas sr ON sr.schema_id = tr.schema_id
        JOIN sys.columns cr ON cr.object_id = fkc.referenced_object_id AND cr.column_id = fkc.referenced_column_id
        ORDER BY fk.name, fkc.constraint_column_id
        """
    )
    with engine.connect() as c:
        df = pd.read_sql(q, c)
    fks: dict[str, dict] = {}
    for r in df.itertuples():
        f = fks.setdefault(r.fk, {"ptab": r.ptab, "rtab": r.rtab, "pcols": [], "rcols": []})
        f["pcols"].append(r.pcol)
        f["rcols"].append(r.rcol)
    return list(fks.values())


def main() -> None:
    engine = get_engine(config.MANDANT_DB or "AIRCO")

    con = sqlite3.connect(config.SQLITE_OUT)
    con.execute("PRAGMA foreign_keys=OFF")
    cur = con.cursor()

    tabs = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    present = set(tabs)

    fks = [f for f in grouped_declared_fks(engine)
           if f["ptab"] in present and f["rtab"] in present]
    by_child: dict[str, list] = defaultdict(list)
    for f in fks:
        by_child[f["ptab"]].append(f)
    print(f"{len(fks)} declared FKs apply to exported tables "
          f"({len(by_child)} child tables reference {len({f['rtab'] for f in fks})} parents)")

    def coldefs(t: str) -> list[tuple[str, str]]:
        return [(row[1], row[2] or "") for row in cur.execute(f'PRAGMA table_info("{t}")')]

    for t in tabs:
        if t in META:
            continue
        cols = coldefs(t)
        col_sql = ",\n  ".join(f'"{n}" {ty}'.rstrip() for n, ty in cols)
        fk_sql = ""
        for f in by_child.get(t, []):
            pc = ", ".join(f'"{c}"' for c in f["pcols"])
            rc = ", ".join(f'"{c}"' for c in f["rcols"])
            fk_sql += f',\n  FOREIGN KEY ({pc}) REFERENCES "{f["rtab"]}" ({rc})'
        tmp = f"_fk_{t}"
        cur.execute(f'DROP TABLE IF EXISTS "{tmp}"')
        cur.execute(f'CREATE TABLE "{tmp}" (\n  {col_sql}{fk_sql}\n)')
        cur.execute(f'INSERT INTO "{tmp}" SELECT * FROM "{t}"')
        cur.execute(f'DROP TABLE "{t}"')
        cur.execute(f'ALTER TABLE "{tmp}" RENAME TO "{t}"')
    con.commit()

    # indexes on FK columns (both ends) for navigation performance
    made = 0
    for f in fks:
        for tab, colset in ((f["ptab"], f["pcols"]), (f["rtab"], f["rcols"])):
            for c in colset:
                try:
                    cur.execute(f'CREATE INDEX IF NOT EXISTS "ix_{tab}_{c}" ON "{tab}" ("{c}")')
                    made += 1
                except sqlite3.OperationalError:
                    pass
    con.commit()

    # sanity: count FK constraints now present
    total = 0
    for t in tabs:
        if t in META:
            continue
        total += len(cur.execute(f'PRAGMA foreign_key_list("{t}")').fetchall())
    con.close()
    print(f"Rebuilt with FK constraints. foreign_key_list entries: {total}; indexes ensured: {made}")
    print(f"Restart Datasette / open {config.SQLITE_OUT} in DBeaver to see the ER diagram.")


if __name__ == "__main__":
    main()
