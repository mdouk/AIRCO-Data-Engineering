# AIRCO – Data Engineering: Sage 100 Artikelstamm Extraction

Extract the AIRCO **Sage 100** business entities (articles/materials, products,
suppliers, customers, BOM, prices, ...) **and the relationships between them** into a
single, portable **SQLite file** you can work with locally. Reviewable **Excel**
workbooks are then generated as views from that file. This is the data basis for the
ODOO migration (go-live September).

Nothing here touches AIRCO's production system: we work only from the **full `.bak`**,
restored into a **disposable local SQL Server container**.

## The situation (why this isn't a plain restore)

The only source we have is the **full `AIRCO` `.bak` (~130 GB)**, in a OneDrive-synced
folder on `D:` (`config.BACKUP_HOST_DIR`). Two hard constraints shape everything:

- The `.bak` is a **OneDrive Files-On-Demand** file — it must be fully **downloaded**
  ("Always keep on this device") before anything can read it. While it's a cloud stub,
  size-on-disk is 0 and every read fails.
- The bulk of the 130 GB is the **document/BLOB archive**, not relational data. The
  laptop can't hold a **full** restore (~130 GB `.bak` + ~130 GB restored files). So we
  do a **PARTIAL (piecemeal) restore of the relational filegroup(s) only** — reading the
  whole `.bak` but writing only the small relational data, leaving the document
  filegroup offline.

## Pipeline

```
OneDrive .bak (D:, mounted read-only into the container)
   -> PARTIAL restore of the relational filegroup
   -> discover -> export -> output/sage_extract.sqlite -> Excel views
```

## Prerequisites

- Docker Desktop (running; SQL Server 2022 image already pulled)
- Python 3.13 + packages: `python -m pip install -r requirements.txt`

## Steps

1. **Download the backup fully.** In Explorer, right-click the `.bak` in
   `config.BACKUP_HOST_DIR` -> **"Always keep on this device"** and wait until it shows
   as downloaded (size-on-disk ~130 GB). Nothing below works until this completes.
2. **Move Docker's storage to D:.** The AIRCO DB is a single ~186 GB filegroup, so a
   full ~187 GB restore is required — that fits on D: (269 GB free) but not C: (64 GB),
   where Docker's disk lives by default. In Docker Desktop: **Settings -> Resources ->
   Advanced -> "Disk image location" -> choose a folder on `D:` -> Apply & Restart.**
3. **Start SQL Server** (mounts the D: backup folder read-only at `/backup` via
   `docker-compose.override.yml`):
   ```powershell
   docker compose up -d
   ```
   Optional: `python src/inspect_backup.py` to re-check version/sizes/filegroups.
4. **Full-restore the database** (single filegroup, so no partial option; reads the
   139.7 GB `.bak` from the D: mount, writes the ~186 GB `.mdf` into Docker-on-D:):
   ```powershell
   python src/restore.py --full
   ```
5. **Discover the schema** -> `output/schema_report.xlsx`:
   ```powershell
   python src/discover.py
   ```
6. **Export entities + relationships to one SQLite file:**
   ```powershell
   python src/export_to_sqlite.py --db AIRCO
   ```
   Produces `output/sage_extract.sqlite` — one table per entity, plus `_relationships`
   (declared + inferred FKs), `_tables`, `_columns`, and indexes on the join keys.
7. **Generate Excel views** over the SQLite file (post-discovery):
   ```powershell
   python src/extract_artikelstamm.py
   ```

Teardown / reclaim disk when done: `docker compose down -v`.

## Layout

| Path | Purpose |
|------|---------|
| `docker-compose.yml` | Disposable SQL Server 2022 on `localhost:14330` |
| `docker-compose.override.yml` | Mounts the D: OneDrive backup folder read-only at `/backup` |
| `src/config.py` | Backup location, partial-restore filegroups, DB/table/selection settings |
| `src/db.py` | SQLAlchemy engine (pymssql) |
| `src/inspect_backup.py` | Read backup header/file-list (version, sizes, filegroups) — no restore |
| `src/restore.py` | PARTIAL (default) or `--full` restore of the `.bak` |
| `src/discover.py` | Schema discovery -> `output/schema_report.xlsx` |
| `src/export_to_sqlite.py` | Entities + relationships -> `output/sage_extract.sqlite` |
| `src/extract_artikelstamm.py` | Excel views over the SQLite file (post-discovery) |
| `sql/*.sql` | Source-side helpers (only usable with live DB access — not our case) |
| `output/` | Generated `.sqlite` + workbooks (git-ignored) |

## Notes on Sage 100

- Server `AIRCO-SQL1\SAGESQL2017` = **SQL Server 2017**; Mandant DB = **`AIRCO`**
  (restores fine into the 2022 container). `OLGlobal` holds shared config.
- Article master lives in `KHK*` tables (e.g. `KHKArtikel`). Type distinctions
  (goods / service / combination) + Sales/Purchase flags map onto ODOO's flat
  `product.template` model — the extraction preserves the **original article number**
  so an old<->new number bridge can be built for migration.
- `KHK*` tables likely have **no declared foreign keys**, so `_relationships` mixes
  `declared` and `inferred` (matched on shared key columns).
