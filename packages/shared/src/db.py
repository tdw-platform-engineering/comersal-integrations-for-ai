"""SQL Server connection pool — direct pymssql (no Flask, no Redis).

Connection string from env var SQLSERVER_CONNECTION_STRING.
Format: mssql+pymssql://user:password@host:port/database
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from urllib.parse import unquote, urlparse

import pymssql

_conn_params: dict | None = None


def _parse_connection_string() -> dict:
    cs = os.environ.get("SQLSERVER_CONNECTION_STRING", "")
    if not cs:
        raise RuntimeError("SQLSERVER_CONNECTION_STRING not set")
    parsed = urlparse(cs)
    return {
        "server": parsed.hostname or "localhost",
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": parsed.path.lstrip("/") if parsed.path else "",
        "port": str(parsed.port) if parsed.port else "1433",
    }


def _get_params() -> dict:
    global _conn_params
    if _conn_params is None:
        _conn_params = _parse_connection_string()
    return _conn_params


@contextmanager
def get_connection():
    """Yield a pymssql connection (auto-closed)."""
    params = _get_params()
    conn = pymssql.connect(**params)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_cursor(as_dict: bool = True):
    """Yield a cursor within a connection (both auto-closed)."""
    with get_connection() as conn:
        cursor = conn.cursor(as_dict=as_dict)
        yield cursor, conn
