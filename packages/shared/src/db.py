"""SQL Server connection pool — direct pymssql (no Flask, no Redis).

Connection string from env var SQLSERVER_CONNECTION_STRING.
Format: mssql+pymssql://user:password@host:port/database
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from urllib.parse import unquote, urlparse

import pymssql

logger = logging.getLogger(__name__)

_conn_params: dict | None = None

# Login/query timeouts (seconds). Kept below the Lambda's 30s wall so a network
# or firewall problem surfaces as a raised OperationalError WITH a log line
# instead of a silent 30s hang that dies with no error.
_LOGIN_TIMEOUT = int(os.environ.get("SQLSERVER_LOGIN_TIMEOUT", "10"))
_QUERY_TIMEOUT = int(os.environ.get("SQLSERVER_QUERY_TIMEOUT", "25"))


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
def get_connection(query_timeout: int | None = None):
    """Yield a pymssql connection (auto-closed).

    Args:
        query_timeout: Per-query timeout in seconds. When a single query runs
            longer than this, pymssql raises ``OperationalError`` (the query is
            interrupted). Defaults to ``_QUERY_TIMEOUT``. Pass a small value
            (e.g. 5) for the order-insert path so a hung INSERT fails fast
            instead of eating the whole 30s Lambda wall.
    """
    params = _get_params()
    q_timeout = _QUERY_TIMEOUT if query_timeout is None else query_timeout
    t0 = time.monotonic()
    logger.info(
        "db: connecting to %s:%s db=%s (login_timeout=%ss, query_timeout=%ss)",
        params["server"],
        params["port"],
        params["database"],
        _LOGIN_TIMEOUT,
        q_timeout,
    )
    try:
        conn = pymssql.connect(
            login_timeout=_LOGIN_TIMEOUT,
            timeout=q_timeout,
            **params,
        )
    except Exception:
        logger.exception(
            "db: connection FAILED after %sms (server=%s:%s)",
            round((time.monotonic() - t0) * 1000, 1),
            params["server"],
            params["port"],
        )
        raise
    logger.info("db: connected (%sms)", round((time.monotonic() - t0) * 1000, 1))
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_cursor(as_dict: bool = True, query_timeout: int | None = None):
    """Yield a cursor within a connection (both auto-closed).

    Args:
        as_dict: Return rows as dicts keyed by column name.
        query_timeout: Per-query timeout in seconds (see ``get_connection``).
    """
    with get_connection(query_timeout=query_timeout) as conn:
        cursor = conn.cursor(as_dict=as_dict)
        yield cursor, conn
