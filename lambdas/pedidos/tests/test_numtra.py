"""Unit tests for NUMTRA generation via NEXT VALUE FOR dbo.seq_pedidos_glory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("SQLSERVER_CONNECTION_STRING", "mssql+pymssql://u:p@host:1433/db")
    # Defaults: PIA- + 10 digits, sequence dbo.seq_pedidos_glory.
    monkeypatch.delenv("NAV_NUMTRA_PREFIX", raising=False)
    monkeypatch.delenv("NAV_NUMTRA_PAD_LENGTH", raising=False)
    monkeypatch.delenv("NAV_NUMTRA_SEQUENCE", raising=False)


def _cursor(next_val):
    """A fake pymssql cursor whose NEXT VALUE FOR query returns next_val."""
    cursor = MagicMock()
    cursor.fetchone.return_value = None if next_val is None else {"next_val": next_val}
    return cursor


def test_next_numtra_uses_sequence_value_directly():
    """NEXT VALUE FOR returns the correlativo — used as-is, no +1."""
    from src.numtra import next_numtra

    cursor = _cursor(102)
    assert next_numtra(cursor) == "PIA-0000000102"
    # It must have consumed the sequence via NEXT VALUE FOR.
    sql = cursor.execute.call_args[0][0]
    assert "NEXT VALUE FOR" in sql
    assert "dbo.seq_pedidos_glory" in sql


def test_next_numtra_pads_to_ten_digits():
    from src.numtra import next_numtra

    assert next_numtra(_cursor(7)) == "PIA-0000000007"


def test_next_numtra_tuple_cursor():
    """Cursor returning a tuple (as_dict=False) is also supported."""
    from src.numtra import next_numtra

    cursor = MagicMock()
    cursor.fetchone.return_value = (250,)
    assert next_numtra(cursor) == "PIA-0000000250"


def test_next_numtra_raises_when_no_value():
    """No value back (sequence missing / no UPDATE perm) → RuntimeError."""
    from src.numtra import next_numtra

    with pytest.raises(RuntimeError):
        next_numtra(_cursor(None))


def test_next_numtra_custom_prefix_and_pad():
    """A different company's series (e.g. APP + 6 digits) formats correctly."""
    from src import numtra

    cursor = _cursor(8)
    with (
        patch("src.numtra.NAV_NUMTRA_PREFIX", "APP"),
        patch("src.numtra.NAV_NUMTRA_PAD_LENGTH", 6),
    ):
        assert numtra.next_numtra(cursor) == "APP000008"
