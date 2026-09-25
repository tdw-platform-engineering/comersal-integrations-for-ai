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

# Login/query timeouts (seconds). Deliberately kept LOW so the worst-case sum
# of every DB step in one order (validate connect + validate query + insert
# connect + insert step) stays comfortably under the Lambda's 30s wall. That
# guarantees our own except/finally cleanup (rollback + connection close) always
# runs — if instead a step ran long enough to hit the 30s Lambda timeout, the
# runtime is hard-killed and NO Python cleanup executes, leaving the rollback to
# SQL Server's (delayed) orphaned-connection reaping. Keeping these tight avoids
# that path entirely. Override per-env via the SQLSERVER_* env vars if needed.
_LOGIN_TIMEOUT = int(os.environ.get("SQLSERVER_LOGIN_TIMEOUT", "5"))
_QUERY_TIMEOUT = int(os.environ.get("SQLSERVER_QUERY_TIMEOUT", "8"))

# When enabled, EVERY SQL statement (with params + timing) is logged at INFO via
# a transparent cursor proxy. Turned ON by default right now to prove out what
# the pedidos Lambda actually sends to NAV (the client insists there is no lock
# on the order table — this shows the exact statements + where they stall).
# Flip SQLSERVER_ECHO=0 to silence once the investigation is done.
_SQL_ECHO = os.environ.get("SQLSERVER_ECHO", "1") not in ("0", "false", "False", "")


def _truncate(val: object, limit: int = 2000) -> str:
    s = repr(val)
    return s if len(s) <= limit else s[:limit] + f"...<+{len(s) - limit} chars>"


class _LoggingCursor:
    """Transparent proxy around a pymssql cursor that logs each SQL statement.

    Logs the operation + params BEFORE running (so a statement that then hangs
    is still visible) and the row/elapsed AFTER. Everything else (fetchone,
    fetchall, iteration, attributes) is delegated to the real cursor unchanged.
    """

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, operation, params=None):
        t0 = time.monotonic()
        sql_flat = " ".join(str(operation).split())
        logger.info("sql.execute >>> %s | params=%s", sql_flat, _truncate(params))
        try:
            if params is not None:
                result = self._cursor.execute(operation, params)
            else:
                result = self._cursor.execute(operation)
        except Exception:
            logger.exception(
                "sql.execute FAILED after %sms >>> %s",
                round((time.monotonic() - t0) * 1000, 1),
                sql_flat,
            )
            raise
        logger.info(
            "sql.execute <<< done rowcount=%s (%sms)",
            getattr(self._cursor, "rowcount", "?"),
            round((time.monotonic() - t0) * 1000, 1),
        )
        return result

    def executemany(self, operation, seq_of_params):
        t0 = time.monotonic()
        logger.info(
            "sql.executemany >>> %s | batches=%s",
            " ".join(str(operation).split()),
            len(seq_of_params) if hasattr(seq_of_params, "__len__") else "?",
        )
        try:
            result = self._cursor.executemany(operation, seq_of_params)
        except Exception:
            logger.exception(
                "sql.executemany FAILED after %sms >>> %s",
                round((time.monotonic() - t0) * 1000, 1),
                " ".join(str(operation).split()),
            )
            raise
        logger.info("sql.executemany <<< done (%sms)", round((time.monotonic() - t0) * 1000, 1))
        return result

    def __getattr__(self, name):
        # Delegate everything else (fetchone/fetchall/rowcount/close/...).
        return getattr(self._cursor, name)

    def __iter__(self):
        return iter(self._cursor)


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
        if _SQL_ECHO:
            cursor = _LoggingCursor(cursor)
        yield cursor, conn
