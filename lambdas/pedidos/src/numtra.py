"""NUMTRA generation — consume the dbo.seq_pedidos_glory SQL Server SEQUENCE.

Format: PIA-NNNNNNNNNN (prefix + zero-padded correlativo).

Design (confirmed with NAV): the SEQUENCE is the source of truth for the order
correlativo. Unlike an IDENTITY it survives ENC/DET table cleanups (a TRUNCATE
does not reset it). The bot ADVANCES the correlativo by consuming the sequence
with ``NEXT VALUE FOR`` — which atomically returns the next value AND advances
the sequence in one step, so concurrent orders can never get the same number.

``next_numtra(cursor)`` runs inside the caller's OPEN transaction (the same
transaction that inserts the header + detail), so "advance the correlativo" and
"insert the order" commit together — exactly one sequence value per persisted
order. Consuming the sequence requires the UPDATE permission on the object
(verified: the connection login has it).

The returned integer IS the NUMTRA number (no +1) — ``NEXT VALUE FOR`` already
advanced it.
"""

from __future__ import annotations

import logging

from config import (
    NAV_NUMTRA_PAD_LENGTH,
    NAV_NUMTRA_PREFIX,
    NAV_NUMTRA_SEQUENCE,
)

logger = logging.getLogger(__name__)


def next_numtra(cursor) -> str:  # noqa: ANN001 — pymssql cursor, kept transaction-local
    """Consume the sequence within the caller's transaction and build the NUMTRA.

    Args:
        cursor: An OPEN pymssql cursor whose connection owns the insert
            transaction. ``NEXT VALUE FOR`` runs on it so the sequence advance
            and the order insert are one atomic unit.

    Returns:
        The formatted NUMTRA (e.g. "PIA-0000000102").

    Raises:
        RuntimeError: If the sequence value cannot be obtained.
    """
    cursor.execute(f"SELECT NEXT VALUE FOR {NAV_NUMTRA_SEQUENCE} AS next_val")
    row = cursor.fetchone()
    # pymssql returns a dict (as_dict=True) or a tuple depending on the cursor.
    if isinstance(row, dict):
        value = row.get("next_val")
    elif row:
        value = row[0]
    else:
        value = None

    if value is None:
        raise RuntimeError(
            f"NEXT VALUE FOR {NAV_NUMTRA_SEQUENCE} no devolvió valor "
            "(¿existe la secuencia y el usuario tiene permiso UPDATE?)"
        )

    seq = int(value)
    numtra = f"{NAV_NUMTRA_PREFIX}{seq:0{NAV_NUMTRA_PAD_LENGTH}d}"
    logger.info("Generated NUMTRA from sequence: %s (seq value=%s)", numtra, seq)
    return numtra
