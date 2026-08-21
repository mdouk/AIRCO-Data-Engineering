"""Central configuration for the Sage 100 extraction.

Only the local, disposable container is referenced here — never AIRCO production.
After running discover.py, set MANDANT_DB and confirm the table names below.
"""

# --- Local SQL Server container (from docker-compose.yml) ---
HOST = "localhost"
PORT = 14330
USER = "sa"
PASSWORD = "Sage_Dev_2026!"  # local-only dev password

# Connect to 'master' for restore/discovery; to the Mandant DB for extraction.
SYSTEM_DB = "master"

# --- Where to read FROM ---------------------------------------------------
# "local"  -> the disposable Docker container (a restored .bak)
# "remote" -> a live read-only login on the Sage server (e.g. Hetzner)
SOURCE = "local"

# Live read-only connection (used only when SOURCE == "remote").
REMOTE_HOST = ""
REMOTE_PORT = 1433
REMOTE_USER = "mosaiic_ro"
REMOTE_PASSWORD = ""

# --- Local 130 GB backup (OneDrive-synced folder on D:) -------------------
# The full AIRCO .bak lives here on the host. docker-compose.override.yml mounts
# this folder at BACKUP_CONTAINER_DIR (read-only) so the container reads the .bak
# in place — no 130 GB copy anywhere. restore.py / inspect_backup.py default to these.
BACKUP_HOST_DIR = r"D:\Airco Systemdruckluft GmbH\Airco Systemdruckluft GmbH\Projekt Big-Picture - Backup SQL"
BACKUP_CONTAINER_DIR = "/backup"

# inspect_backup.py confirmed the AIRCO DB has a SINGLE filegroup (PRIMARY, ~186 GB) —
# documents and relational tables are mixed together, so a partial/filegroup restore is
# NOT possible. We must do a FULL restore (~187 GB written). That needs Docker's data
# disk relocated to D: (269 GB free); C: (64 GB) is too small. See README "Full restore".
RESTORE_PARTIAL = False
RESTORE_FILEGROUPS = ["PRIMARY"]

# --- Set after discovery ---
# The per-company (Mandant) database that holds KHKArtikel & friends.
# Confirmed from SSMS: server AIRCO-SQL1\SAGESQL2017 (SQL Server 2017), Mandant = "AIRCO".
# "OLGlobal" holds Sage's shared/global config (may be needed for some lookups).
MANDANT_DB = "AIRCO"

# Table names are confirmed by discover.py; these are the *expected* Sage 100 names
# and are used only as search hints during discovery.
EXPECTED_ARTICLE_TABLES = [
    "KHKArtikel",            # article master (core)
    "KHKArtikelLagerbestand",
    "KHKArtikelKurztexte",
    "KHKArtikelLieferanten",
    "KHKVKPreise",           # sales prices
    "KHKEKPreise",           # purchase prices
    "KHKStueckliste",        # BOM header
    "KHKStuecklistePosition",
    "KHKWarengruppen",       # product groups
]

# Substrings used to surface relevant tables during discovery.
DISCOVERY_KEYWORDS = ["artikel", "stueck", "stück", "warengr", "preis", "nummer", "lager"]

OUTPUT_DIR = "output"

# --- SQLite export (export_to_sqlite.py) ----------------------------------
SQLITE_OUT = "output/sage_extract.sqlite"

# Which source tables to pull into the SQLite file:
#   "entities" -> tables matching ENTITY_KEYWORDS + everything they are FK-linked to
#   "khk"      -> all tables whose name contains "khk"
#   "all"      -> every user table (records only)
TABLE_SELECTION = "entities"

ENTITY_KEYWORDS = [
    "artikel", "produkt", "material", "stueck", "stück", "bom",
    "lieferant", "kunde", "adresse", "warengr", "preis", "lager", "einheit",
]

# In "entities" mode, drop tables that match a keyword but are transactional / history /
# statistics / system rather than master data + mappings (vouchers, bookings, logs, ...).
EXCLUDE_SUBSTRINGS = [
    "beleg", "buchung", "journal", "bewegung", "bewertung", "archiv", "histo",
    "logbuch", "protokoll", "print", "import", "abgleich", "dispo", "planung",
    "webshop", "stat", "opportunity", "vermietung", "liquid", "kosten",
]
EXCLUDE_PREFIXES = ["tkhk", "bak_", "usys", "fs", "dt", "tmp", "bs", "bcs"]

# Always include these in "entities" mode (important but not keyword/FK-reachable).
EXTRA_TABLES = ["KHKNummernkreise"]

# Infer relationships when the DB has few/no declared foreign keys.
INFER_RELATIONSHIPS = True
# Column names too generic to treat as a relationship key on their own.
INFERENCE_STOPLIST = {
    "mandant", "id", "guid", "nummer", "pos", "position", "zeile",
    "sdobjmemo", "dispositionsart", "aktiv", "gesperrt",
}

