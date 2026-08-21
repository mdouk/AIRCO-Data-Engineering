# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Not a typical app — this is a **one-off data-engineering pipeline** for a consulting
engagement. mosaiic GmbH is extracting the legacy **Sage 100** business data of client
**AIRCO-Systems GmbH** so it can be cleaned and migrated into **Odoo** (go-live targeted
September 2026). The deliverable is a single portable **SQLite file**
(`output/sage_extract.sqlite`) holding the business entities (articles/materials,
products, suppliers, customers, BOM, prices, product groups, number ranges, warehouses)
**and the relationships between them**; Excel workbooks are generated as views on top.

Read `README.md` for the run book, `Dokumentation_Data_Engineering_DE.md` for the
plain-language (German) write-up, and `Transkript.txt` + `pptx_text.txt` (extracted from
the client's `.docx`/`.pptx`) for the source requirements and IT landscape.

## Pipeline (the whole app is these steps)

```
OneDrive .bak (D:, ~130 GB)  ->  FULL restore into Docker-on-D:  ->  discover
   ->  export (curated entities + relationships)  ->  sage_extract.sqlite
   ->  add real FKs  ->  browse (Datasette / DBeaver) / Excel views
```

```powershell
python -m pip install -r requirements.txt   # pandas, openpyxl, XlsxWriter, SQLAlchemy, pymssql, datasette
docker compose up -d                         # disposable SQL Server 2022 on localhost:14330
python src/inspect_backup.py                 # header/file-list: version, sizes, FILEGROUPS (no restore)
python src/restore.py --full                 # FULL restore (~187 GB; single filegroup -> no partial)
python src/restore_progress.py               # optional: live restore % + ETA while restore.py runs
python src/discover.py                       # -> output/schema_report.xlsx (DBs, KHK* tables, columns)
python src/export_to_sqlite.py --db AIRCO    # -> output/sage_extract.sqlite (entities + relationships)
python src/add_foreign_keys.py               # rebuild the SQLite with real FK constraints (ER diagram)
python -m datasette serve output/sage_extract.sqlite --port 8001   # browse at http://localhost:8001
docker compose down -v                       # teardown, reclaim ~187 GB on D:
```

Syntax-check after edits (there is no test suite): `python -m py_compile src/*.py`

## Architecture

- `src/config.py` — single source of truth. `SOURCE` (`local` Docker restore vs `remote`
  live login), `MANDANT_DB="AIRCO"`, `BACKUP_HOST_DIR` (the D: OneDrive folder),
  `RESTORE_PARTIAL=False` (AIRCO is single-filegroup), table-selection keywords +
  `EXCLUDE_SUBSTRINGS`/`EXCLUDE_PREFIXES`/`EXTRA_TABLES`, relationship-inference stoplist.
- `src/db.py` — SQLAlchemy engine via **pymssql** (TDS protocol → **no Microsoft ODBC
  driver needed**). `get_engine()` targets local or remote per `SOURCE`; `pool_pre_ping`
  recovers dead connections.
- `src/inspect_backup.py` — reads `RESTORE HEADERONLY`/`FILELISTONLY` from the D:-mounted
  `.bak` (cheap metadata): source version, restored footprint, **filegroup layout**.
- `src/restore.py` — restores the `.bak` (read in place from `/backup`). `--full` for the
  whole DB (what AIRCO needs); the default partial/filegroup path exists for DBs that
  isolate documents on a separate filegroup. Prints source SQL version; waits for the
  container via `connect_retry`.
- `src/restore_progress.py` — queries `sys.dm_exec_requests.percent_complete` for a live
  restore %/ETA (plus Docker-disk growth) from a second connection.
- `src/discover.py` — inventories databases/tables/columns → `output/schema_report.xlsx`.
- `src/export_to_sqlite.py` — the core deliverable. Discovers tables + FK metadata from
  the live catalog, selects a **curated** entity set (keyword seeds + declared-FK closure,
  minus transactional/history/system tables), streams each table in 50k-row chunks into
  one SQLite file, and writes `_relationships` (declared + inferred), `_tables`,
  `_columns` + indexes on join keys. `build_select()` neutralises pymssql-hostile columns.
- `src/add_foreign_keys.py` — post-processes the SQLite: rebuilds each table with real
  `FOREIGN KEY` constraints (declared FKs only, grouped into composites) so DBeaver draws
  an ER diagram and Datasette shows clickable links. Copies data within SQLite.
- `sql/*.sql` — **source-side helpers, run in SSMS with live DB access** (we DON'T have
  that here, so they're unused): `table_sizes.sql` (read-only sizes) and
  `make_extract_bak.sql` (build a small, document-excluding `.bak`).

## Source system (confirmed)

- Server `AIRCO-SQL1\SAGESQL2017`, **SQL Server 2017** (14.x), **internal network only**
  (no external login → we work from the backup file).
- Databases: **`AIRCO`** = Mandant DB with the article master (`KHKArtikel` = 263,933
  articles × 114 cols); `OLGlobal` = Sage shared/global config; `OLReweAbf` = accounting;
  `Spielwiese`/`Test` = sandboxes to ignore.
- **AIRCO has ~179 *declared* FK constraints** — Sage 100 DOES define real FKs here, so
  relationships are largely trustworthy (not purely app-enforced as first assumed). Keys
  are typically composite on `Mandant` + a business key (e.g. `Artikelnummer`).
- Article master key columns (map to Odoo): `Artikelnummer`, `Bezeichnung1/2`, `Matchcode`,
  `Artikelgruppe`, `Ersatzartikelnummer`, `Hersteller`/`HArtikelnummer`,
  `IstVerkaufsartikel`/`IstBestellartikel` (= Odoo Sales-OK/Purchase-OK), unit fields,
  `Stuecklistentyp` (BOM). Free-for-all article number `999` collects junk (per transcript).

## Critical constraints & gotchas — read before acting

- **The only source is the full `AIRCO` `.bak` (~130 GB compressed / 186 GB restored)** at
  `D:\Airco Systemdruckluft GmbH\...\Projekt Big-Picture - Backup SQL`
  (= `config.BACKUP_HOST_DIR`). The bulk is one document/BLOB table, **`BCSPjmDokumente`
  (~169 GB)** — excluded from the export by keyword + `bcs` prefix. The relational tables
  we need are only tens of MB.
- **The `.bak` is a OneDrive Files-On-Demand file** — a cloud stub with 0 bytes on disk
  until "Always keep on this device" downloads all 130 GB. Any read before then fails
  (I/O 1117 / "Cloudvorgang timed out"). Verify with **size-on-disk**, not Explorer's size.
- **Single PRIMARY filegroup → full restore only** (~187 GB written). It fits on **D:**
  but not C: (64 GB) where Docker's vhdx lives by default, so **Docker Desktop's disk
  image was relocated to `D:\DockerData`** (Settings → Resources → Advanced).
- **Cap SQL Server memory:** `docker-compose.yml` sets `MSSQL_MEMORY_LIMIT_MB=8192`.
  Without it, a heavy read spikes SQL Server and Docker OOM-kills the container (exit 255).
  AIRCO persists in the `mssql-data` volume, so a killed container just needs restarting —
  no re-restore.
- **pymssql read hazards (fixed in `export_to_sqlite.build_select`):** a `rowversion`/
  `Timestamp` (and other binary/LOB) column plus SQLAlchemy `stream_results=True` kills
  the connection with error 20047 "DBPROCESS is dead". Fix: neutralise binary/LOB columns
  (binary/rowversion → NULL, text/ntext/xml/sql_variant → nvarchar(max)) and do NOT stream.
  Each table export is wrapped in try/except so one bad table can't abort the run.
- **Boolean flags = integer -1 (true) / 0 (false):** Sage stores its `Ist*`/`Hat*` flags
  as **integers where -1 = true** (VB/Access-style), NOT as SQL `bit` (the DB has only one
  real `bit` column). This is the source value, not a driver artifact — the SQLite keeps it
  faithfully as `-1`/`0`. Always test **non-zero = true** (`!= 0`), never `== 1`. The Excel
  renders `Ja`/`Nein` via `extract_artikelstamm.py`. Do NOT blindly normalise -1→1 (can't
  reliably tell flags from other int columns, and -1 is the faithful source value).
- **German data:** umlauts (stored correctly as Unicode — the Windows console mis-renders
  them, the data is fine), comma-decimals, long-text with embedded delimiters/newlines.
  This is why the deliverable is SQLite (types + encoding preserved), not raw CSV.
- **SQLite has no ALTER-ADD-FK:** `add_foreign_keys.py` recreates tables to add FKs.
  FK **enforcement stays OFF** (the extract needn't satisfy every constraint); DBeaver/
  Datasette read the schema metadata regardless.
- **Never touch production.** All work happens against the restored copy in a disposable
  container; the source `.bak` is mounted **read-only**.

## Viewing the data

- **Datasette** (browser): `python -m datasette serve output/sage_extract.sqlite --port 8001`
  → http://localhost:8001. FKs render as clickable links; `_relationships` documents all
  mappings (declared + inferred).
- **DBeaver** (desktop): New Connection → SQLite → `output/sage_extract.sqlite` →
  *View Diagram* for the ER diagram.

## Deliverable status (2026-08-17)

`output/sage_extract.sqlite` (~374 MB) produced & verified (`integrity_check: ok`):
~70 curated tables, `KHKArtikel` 263,933 rows, **419 declared + 1,537 inferred**
relationships documented in `_relationships`, and **46 real composite FK constraints**
promoted into the schema for the ER diagram. FK-closure also pulled in some non-master
tables (`KHKOpHauptsatz`/`KHKOpNebensatz` accounting, empty PPS tables) — candidates to
trim. Not yet done: Excel `Artikelstamm` view (`extract_artikelstamm.py`), old↔new number
mapping, final teardown.

## Environment

Windows 11 / PowerShell. Docker Desktop (WSL2, data on `D:\DockerData`, 16 GB).
`restore/`, `output/`, `*.xlsx`/`*.sqlite`/`*.bak` are git-ignored (client data must never
be committed). Contacts: Oliver (SQL/infra), Vanessa (content/functional), Thorsten
(owner/suppliers), Jens (owner).
