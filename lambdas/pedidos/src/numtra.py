"""NUMTRA generation — read the dbo.seq_pedidos_glory SQL Server SEQUENCE.

Format: PIA-NNNNNNNNNN (prefix + zero-padded correlativo).

Design (confirmed with NAV): the SEQUENCE is the source of truth for the order
correlativo. Unlike an IDENTITY it survives ENC/DET table cleanups (a TRUNCATE
does not reset it). **NAV's order INSERT is what ADVANCES the sequence**; the bot
only READS `sys.sequences.current_value` and adds `increment` to build the NUMTRA
to write into the order. The bot never consumes/modifies the sequence, so
read-only (db_datareader) access is enough — no UPDATE grant needed.

`current_value` reflects the highest value the sequence has reached. The bot's
rule is "read the current correlativo and add 1" → `current_value + increment`.
Note on first use: a freshly created sequence reports `current_value = start_value`
(e.g. 100), so the first generated NUMTRA is start+increment (101). After NAV
inserts a pedido and advances the sequence, `current_value` tracks the last value
NAV consumed and the bot reads that + increment for the next order.
"""

from __future__ import annotations

import logging

from config import (
    NAV_NUMTRA_PAD_LENGTH,
    NAV_NUMTRA_PREFIX,
    NAV_NUMTRA_SEQUENCE,
)
from db import get_cursor

logger = logging.getLogger(__name__)


def get_next_numtra() -> str:
    """Build the next NUMTRA from the dbo.seq_pedidos_glory sequence.

    Reads the sequence's current_value + increment (read-only) and formats it as
    ``{prefix}{next:0{pad}d}`` (e.g. "PIA-0000000101").

    Raises:
        RuntimeError: If the sequence does not exist or cannot be read.
    """
    # Split "schema.name" (default schema = dbo).
    parts = NAV_NUMTRA_SEQUENCE.split(".")
    seq_schema, seq_name = (parts[0], parts[1]) if len(parts) == 2 else ("dbo", parts[0])

    with get_cursor() as (cursor, _conn):
        cursor.execute(
            """
            SELECT CAST(current_value AS BIGINT) AS current_value,
                   CAST(increment     AS BIGINT) AS increment
            FROM sys.sequences
            WHERE name = %s AND SCHEMA_NAME(schema_id) = %s
            """,
            (seq_name, seq_schema),
        )
        row = cursor.fetchone()

    if not row or row.get("current_value") is None:
        raise RuntimeError(
            f"No se pudo leer la secuencia {seq_schema}.{seq_name} "
            "(¿existe y el usuario tiene lectura?)"
        )

    current = int(row["current_value"])
    increment = int(row.get("increment") or 1)
    next_seq = current + increment

    numtra = f"{NAV_NUMTRA_PREFIX}{next_seq:0{NAV_NUMTRA_PAD_LENGTH}d}"
    logger.info("Generated NUMTRA from sequence: %s (seq current=%s)", numtra, current)
    return numtra
