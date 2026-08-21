"""Show live progress of the running RESTORE.

SQL Server reports RESTORE progress in sys.dm_exec_requests (percent_complete +
estimated time remaining). This queries it from a second connection while the restore
runs in another session, and also shows the Docker disk growth / D: free as a
secondary signal. Safe to run as often as you like.

    python src/restore_progress.py
"""
from __future__ import annotations

import os
import shutil

from db import raw_connection

VHDX = r"D:\DockerData\DockerDesktopWSL\disk\docker_data.vhdx"
DATA_DRIVE = "D:\\"


def main() -> None:
    try:
        conn = raw_connection(autocommit=True)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT r.command,
                   r.percent_complete,
                   r.total_elapsed_time / 60000.0      AS elapsed_min,
                   r.estimated_completion_time / 60000.0 AS remaining_min
            FROM sys.dm_exec_requests r
            WHERE r.command LIKE 'RESTORE%'
            """
        )
        rows = cur.fetchall()
        if rows:
            for cmd, pct, elapsed, remaining in rows:
                print(f"{cmd}: {pct:5.1f}% complete | "
                      f"elapsed {elapsed:.1f} min | ~{remaining:.1f} min left")
        else:
            print("No RESTORE in progress (it has finished, failed, or not started writing yet).")
        conn.close()
    except Exception as e:  # noqa: BLE001
        print(f"(could not query SQL Server yet: {e})")

    if os.path.exists(VHDX):
        print(f"docker disk: {os.path.getsize(VHDX) / 1e9:.1f} GB (grows toward ~220 GB)")
    free = shutil.disk_usage(DATA_DRIVE).free / 1e9
    print(f"D: free   : {free:.1f} GB")


if __name__ == "__main__":
    main()
