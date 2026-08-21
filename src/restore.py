"""Restore the Sage 100 .bak into the local SQL Server container.

Because the local disk cannot hold a FULL restore of the 130 GB backup (which is
mostly the document/BLOB archive), the default is a PARTIAL (piecemeal) restore of
only the relational filegroup(s) in config.RESTORE_FILEGROUPS (default PRIMARY),
leaving the document filegroup(s) offline. We read the whole .bak but only WRITE the
small relational data files — that fits.

The .bak is read in place from the OneDrive folder on D:, mounted read-only into the
container at config.BACKUP_CONTAINER_DIR by docker-compose.override.yml.

Usage:
    python src/restore.py                       # partial restore of PRIMARY (default)
    python src/restore.py --full                # full restore (needs ~2x the DB size free)
    python src/restore.py --filegroups PRIMARY,Stammdaten
    python src/restore.py --db AIRCO            # override the restored DB name
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import time

import config
from db import raw_connection


def connect_retry(retries: int = 40, delay: int = 3):
    """Wait for the freshly-started container to accept connections."""
    last = None
    for i in range(retries):
        try:
            return raw_connection(autocommit=True)
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  waiting for SQL Server to accept connections... ({i + 1}/{retries})")
            time.sleep(delay)
    sys.exit(f"Could not connect to the container: {last}")

CONTAINER_DATA_DIR = "/var/opt/mssql/data"

_SQL_MAJOR = {16: "2022", 15: "2019", 14: "2017", 13: "2016",
              12: "2014", 11: "2012", 10: "2008/R2", 9: "2005"}
CONTAINER_MAJOR = 16  # docker-compose uses mssql/server:2022-latest


def find_backups(host_dir: str) -> list[str]:
    baks = sorted(glob.glob(os.path.join(host_dir, "*.bak")))
    if not baks:
        sys.exit(f"No .bak found in {host_dir}")
    return [os.path.basename(b) for b in baks]


def _rows(cur) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def gb(v) -> float:
    try:
        return float(v) / 1e9
    except (TypeError, ValueError):
        return 0.0


def print_header(cur, disk_path: str) -> dict:
    cur.execute(f"RESTORE HEADERONLY FROM DISK = N'{disk_path}'")
    hdr = _rows(cur)[0]
    major = hdr.get("SoftwareVersionMajor")
    prod = _SQL_MAJOR.get(major, f"major {major}")
    print(f"  Source DB        : {hdr.get('DatabaseName')}")
    print(f"  Made with        : SQL Server {prod}")
    print(f"  Backup finished  : {hdr.get('BackupFinishDate')}")
    if isinstance(major, int) and major > CONTAINER_MAJOR:
        print(f"  !! Backup is NEWER than the 2022 container; bump the image to {prod}.")
    return hdr


def get_file_list(cur, disk_path: str) -> list[dict]:
    cur.execute(f"RESTORE FILELISTONLY FROM DISK = N'{disk_path}'")
    return _rows(cur)


def restore_one(cur, disk: str, db_override: str | None,
                partial: bool, filegroups: list[str]) -> str:
    hdr = print_header(cur, disk)
    files = get_file_list(cur, disk)

    # Summarise filegroups so the operator sees what is included vs skipped.
    fg_size: dict[str, float] = {}
    for f in files:
        if f["Type"] != "L":
            fg = f.get("FileGroupName") or "(none)"
            fg_size[fg] = fg_size.get(fg, 0.0) + gb(f.get("Size"))
    print("  Filegroups in backup:")
    for fg, s in sorted(fg_size.items(), key=lambda kv: kv[1], reverse=True):
        mark = "KEEP" if (not partial or fg in filegroups) else "skip (offline)"
        print(f"    {fg:<20} {s:8.1f} GB   [{mark}]")

    db_name = db_override or hdr.get("DatabaseName") or files[0]["LogicalName"]

    # Choose which files to bring online: log always; data only for kept filegroups.
    def keep(f) -> bool:
        return f["Type"] == "L" or (not partial) or (f.get("FileGroupName") in filegroups)

    move_clauses, data_seen = [], False
    for f in files:
        if not keep(f):
            continue
        if f["Type"] == "D":
            ext, data_seen = (".mdf" if not data_seen else ".ndf"), True
        elif f["Type"] == "L":
            ext = ".ldf"
        else:
            ext = ".dat"
        target = f"{CONTAINER_DATA_DIR}/{db_name}_{f['LogicalName']}{ext}"
        move_clauses.append(f"MOVE N'{f['LogicalName']}' TO N'{target}'")

    if partial:
        fg_clause = ", ".join(f"FILEGROUP='{fg}'" for fg in filegroups)
        stmt = (f"RESTORE DATABASE [{db_name}] {fg_clause} FROM DISK = N'{disk}' "
                f"WITH PARTIAL, REPLACE, RECOVERY, " + ", ".join(move_clauses))
        print(f"  Restoring PARTIAL ({', '.join(filegroups)}) as '{db_name}' — "
              f"reads the full .bak, writes only the kept filegroup(s)...")
    else:
        stmt = (f"RESTORE DATABASE [{db_name}] FROM DISK = N'{disk}' WITH REPLACE, "
                + ", ".join(move_clauses))
        print(f"  Restoring FULL as '{db_name}' (needs ~2x the DB size free)...")

    cur.execute(stmt)
    try:
        while cur.nextset():  # drain progress messages so the restore completes
            pass
    except Exception:
        pass
    print(f"  -> '{db_name}' restored.")
    return db_name


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host-dir", default=config.BACKUP_HOST_DIR,
                    help="Host folder holding the .bak (default: config.BACKUP_HOST_DIR)")
    ap.add_argument("--container-dir", default=config.BACKUP_CONTAINER_DIR,
                    help="Where that folder is mounted in the container")
    ap.add_argument("--db", help="Restored DB name (default: from backup header)")
    ap.add_argument("--full", action="store_true",
                    help="Full restore instead of the partial default (needs ~2x disk)")
    ap.add_argument("--filegroups",
                    default=",".join(config.RESTORE_FILEGROUPS),
                    help="Comma-separated filegroups to bring online in a partial restore")
    args = ap.parse_args()

    partial = config.RESTORE_PARTIAL and not args.full
    filegroups = [fg.strip() for fg in args.filegroups.split(",") if fg.strip()]

    baks = find_backups(args.host_dir)
    print(f"Found {len(baks)} backup(s): {', '.join(baks)}")

    conn = connect_retry()
    cur = conn.cursor()
    restored = []
    for name in baks:
        disk = f"{args.container_dir}/{name}"
        print(f"\n=== {name} ===")
        restored.append(restore_one(cur, disk, args.db, partial, filegroups))
    conn.close()

    print(f"\nDone. Restored on localhost:14330: {', '.join(restored)}")
    print("Next: run discover.py, then export_to_sqlite.py --db AIRCO")


if __name__ == "__main__":
    main()
