"""NUMTRA generation — direct SQL Server query (no Athena).

Format: PAWS-NNNNNNNNNN (10-digit zero-padded sequential).
Queries the pedidos ENC table directly for MAX(NUMTRA) matching prefix.
"""

from __future__ import annotations

import logging
import re

from config import NAV_NUMTRA_PAD_LENGTH, NAV_NUMTRA_PREFIX, NAV_PEDIDO_ENC_TABLE
from db import get_cursor

logger = logging.getLogger(__name__)

_PREFIX = NAV_NUMTRA_PREFIX
_PAD_LENGTH = NAV_NUMTRA_PAD_LENGTH
_EXTRACT_RE = re.compile(rf"^{re.escape(_PREFIX)}(\d+)$")


def get_next_numtra() -> str:
    """Get next NUMTRA directly from SQL Server.

    Returns:
        Next NUMTRA string (e.g. "PAWS-0000000001").

    Raises:
        RuntimeError: If the query fails.
    """
    query = f"""
        SELECT TOP 1 NUMTRA
        FROM {NAV_PEDIDO_ENC_TABLE}
        WHERE NUMTRA LIKE %s
        ORDER BY NUMTRA DESC
    """

    with get_cursor() as (cursor, _conn):
        cursor.execute(query, (f"{_PREFIX}%",))
        row = cursor.fetchone()

    if not row:
        next_seq = 1
    else:
        raw = str(row.get("NUMTRA", "") or "")
        match = _EXTRACT_RE.match(raw)
        if match:
            next_seq = int(match.group(1)) + 1
        else:
            next_seq = 1

    numtra = f"{_PREFIX}{next_seq:0{_PAD_LENGTH}d}"
    logger.info("Generated NUMTRA: %s", numtra)
    return numtra
