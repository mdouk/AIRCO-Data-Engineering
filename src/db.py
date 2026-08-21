"""Database connection helpers (pymssql via SQLAlchemy).

pymssql speaks the TDS protocol directly to the container, so no Microsoft ODBC
driver is required on the host.
"""
from __future__ import annotations

import pymssql
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

import config


def _endpoint() -> tuple[str, int, str, str]:
    """(host, port, user, password) for the configured SOURCE."""
    if getattr(config, "SOURCE", "local") == "remote":
        return (config.REMOTE_HOST, config.REMOTE_PORT,
                config.REMOTE_USER, config.REMOTE_PASSWORD)
    return (config.HOST, config.PORT, config.USER, config.PASSWORD)


def get_engine(database: str | None = None) -> Engine:
    """SQLAlchemy engine for pandas.read_sql against the configured source.

    Local (Docker container with a restored .bak) or remote (live read-only login),
    controlled by config.SOURCE.
    """
    host, port, user, password = _endpoint()
    db = database or config.SYSTEM_DB
    url = f"mssql+pymssql://{user}:{password}@{host}:{port}/{db}"
    return create_engine(url, pool_pre_ping=True)


def raw_connection(database: str | None = None, autocommit: bool = False):
    """Raw pymssql connection — needed for RESTORE (must run outside a transaction)."""
    return pymssql.connect(
        server=config.HOST,
        port=str(config.PORT),
        user=config.USER,
        password=config.PASSWORD,
        database=database or config.SYSTEM_DB,
        autocommit=autocommit,
        login_timeout=30,
        timeout=0,  # no query timeout — restores of several GB take a while
    )
