"""Inspect a .bak WITHOUT restoring it.

Reads RESTORE HEADERONLY + FILELISTONLY (cheap metadata, not a full scan) to answer:
  - which SQL Server version made it (restore-compatibility),
  - the restored footprint (does it fit our free disk?),
  - the filegroup layout (can we PARTIAL-restore just the relational data and skip
    the document/BLOB filegroup?).

The backup folder must be mounted into the container (see docker-compose.override.yml,
which mounts it at /backup). Usage:

    python src/inspect_backup.py --host-dir "D:\\...\\Projekt Big-Picture - Backup SQL"
"""
from __future__ import annotations

import argparse
import glob
import os
import time

import config
from db import raw_connection


def _rows(cur) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def connect_retry(retries: int = 40, delay: int = 3):
    last = None
    for i in range(retries):
        try:
            return raw_connection(autocommit=True)
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  waiting for SQL Server to accept connections... ({i + 1}/{retries})")
            time.sleep(delay)
    raise SystemExit(f"Could not connect to the container: {last}")


def gb(v) -> float:
    try:
        return float(v) / 1e9
    except (TypeError, ValueError):
        return 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host-dir", default=config.BACKUP_HOST_DIR,
                    help="Host folder holding the .bak (default: config.BACKUP_HOST_DIR)")
    ap.add_argument("--container-dir", default=config.BACKUP_CONTAINER_DIR,
                    help="Where that folder is mounted inside the container")
    args = ap.parse_args()

    baks = sorted(glob.glob(os.path.join(args.host_dir, "*.bak")))
    if not baks:
        raise SystemExit(f"No .bak found in {args.host_dir}")
    name = os.path.basename(baks[0])
    disk = f"{args.container_dir}/{name}"
    print(f"Inspecting: {disk}\n")

    conn = connect_retry()
    cur = conn.cursor()

    # --- HEADERONLY ---
    cur.execute(f"RESTORE HEADERONLY FROM DISK = N'{disk}'")
    h = _rows(cur)[0]
    major = h.get("SoftwareVersionMajor")
    print("HEADER")
    print(f"  Source DB          : {h.get('DatabaseName')}")
    print(f"  Made with          : SQL Server major {major}")
    print(f"  Backup size        : {gb(h.get('BackupSize')):.1f} GB")
    print(f"  Compressed on disk : {gb(h.get('CompressedBackupSize')):.1f} GB")

    # --- FILELISTONLY ---
    cur.execute(f"RESTORE FILELISTONLY FROM DISK = N'{disk}'")
    files = _rows(cur)
    data_by_fg: dict[str, float] = {}
    log_total = 0.0
    print("\nFILES")
    for f in files:
        size = gb(f.get("Size"))
        typ = f.get("Type")
        fg = f.get("FileGroupName") or ""
        print(f"  [{typ}] {f.get('LogicalName'):<30} FG={fg:<20} {size:8.1f} GB")
        if typ == "L":
            log_total += size
        else:
            data_by_fg[fg] = data_by_fg.get(fg, 0.0) + size

    data_total = sum(data_by_fg.values())
    print("\nSUMMARY")
    for fg, s in sorted(data_by_fg.items(), key=lambda kv: kv[1], reverse=True):
        print(f"  filegroup {fg or '(none)':<20} {s:8.1f} GB")
    print(f"  data total         : {data_total:.1f} GB")
    print(f"  log total          : {log_total:.1f} GB")
    print(f"  full-restore needs : ~{data_total + log_total:.1f} GB free")
    if len(data_by_fg) > 1:
        primary = data_by_fg.get("PRIMARY", 0.0)
        print(f"\n  Multiple filegroups present -> a PARTIAL restore of PRIMARY "
              f"(~{primary:.1f} GB) may skip the document filegroup(s).")
    else:
        print("\n  Single filegroup -> no partial-restore shortcut; full restore only.")
    conn.close()


if __name__ == "__main__":
    main()
