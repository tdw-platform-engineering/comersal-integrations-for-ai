"""Unit tests for NUMTRA generation from the dbo.seq_pedidos_glory sequence."""

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


def _cursor_returning(row):
    cursor = MagicMock()
    cursor.fetchone.return_value = row
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=(cursor, MagicMock()))
    cm.__exit__ = MagicMock(return_value=False)
    return cm, cursor


def test_next_numtra_from_used_sequence():
    """current_value is the last issued value → next = current + increment."""
    from src.numtra import get_next_numtra

    cm, _ = _cursor_returning({"current_value": 11, "increment": 1})
    with patch("src.numtra.get_cursor", return_value=cm):
        assert get_next_numtra() == "PIA-0000000012"


def test_next_numtra_freshly_created_sequence():
    """A freshly created sequence reports current_value = start_value.

    Real dev/prod case: CREATE SEQUENCE ... START WITH 100 → sys.sequences shows
    current_value 100 before first use. Rule "read current + 1" → first NUMTRA is
    101 (start + increment). NAV's INSERT then advances the sequence.
    """
    from src.numtra import get_next_numtra

    cm, _ = _cursor_returning({"current_value": 100, "increment": 1})
    with patch("src.numtra.get_cursor", return_value=cm):
        assert get_next_numtra() == "PIA-0000000101"


def test_next_numtra_respects_increment():
    """Increment other than 1 is honored (not a hardcoded +1)."""
    from src.numtra import get_next_numtra

    cm, _ = _cursor_returning({"current_value": 100, "increment": 5})
    with patch("src.numtra.get_cursor", return_value=cm):
        assert get_next_numtra() == "PIA-0000000105"


def test_next_numtra_missing_increment_defaults_to_1():
    from src.numtra import get_next_numtra

    cm, _ = _cursor_returning({"current_value": 41, "increment": None})
    with patch("src.numtra.get_cursor", return_value=cm):
        assert get_next_numtra() == "PIA-0000000042"


def test_next_numtra_raises_when_sequence_absent():
    """No row (sequence not created / not readable) → RuntimeError, no silent number."""
    from src.numtra import get_next_numtra

    cm, _ = _cursor_returning(None)
    with patch("src.numtra.get_cursor", return_value=cm):
        with pytest.raises(RuntimeError):
            get_next_numtra()


def test_next_numtra_custom_prefix_and_pad():
    """A different company's series (e.g. APP + 6 digits) formats correctly.

    numtra reads the prefix/pad as module-level names imported from config, so
    patch those names directly (matches how the code resolves them at runtime).
    """
    from src import numtra

    cm, _ = _cursor_returning({"current_value": 7, "increment": 1})
    with (
        patch("src.numtra.get_cursor", return_value=cm),
        patch("src.numtra.NAV_NUMTRA_PREFIX", "APP"),
        patch("src.numtra.NAV_NUMTRA_PAD_LENGTH", 6),
    ):
        assert numtra.get_next_numtra() == "APP000008"
