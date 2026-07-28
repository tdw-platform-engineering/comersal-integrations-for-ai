"""Unit tests for catalog data access layer."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("SQLSERVER_CONNECTION_STRING", "mssql+pymssql://u:p@host:1433/db")


@pytest.fixture(autouse=True)
def reset_caches():
    """Reset module-level caches between tests."""
    import catalogs

    catalogs._actividad_catalog = None
    yield


class TestActividadComercial:
    @patch("catalogs.get_cursor")
    def test_load_catalog(self, mock_get_cursor):
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_get_cursor.return_value.__enter__ = MagicMock(
            return_value=(mock_cursor, mock_conn)
        )
        mock_get_cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_cursor.fetchall.return_value = [
            {"codigo": "4711", "descripcion": "VENTA AL POR MENOR"},
            {"codigo": "4712", "descripcion": "FABRICACION DE TEXTILES"},
        ]

        from catalogs import get_actividad_comercial_catalog

        catalog = get_actividad_comercial_catalog()

        assert len(catalog) == 2
        assert catalog["VENTA AL POR MENOR"] == "4711"
        assert catalog["FABRICACION DE TEXTILES"] == "4712"

    @patch("catalogs.get_cursor")
    def test_empty_results(self, mock_get_cursor):
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_get_cursor.return_value.__enter__ = MagicMock(
            return_value=(mock_cursor, mock_conn)
        )
        mock_get_cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = []

        from catalogs import get_actividad_comercial_catalog

        catalog = get_actividad_comercial_catalog()
        assert catalog == {}

    @patch("catalogs.get_cursor")
    def test_lookup_case_insensitive(self, mock_get_cursor):
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_get_cursor.return_value.__enter__ = MagicMock(
            return_value=(mock_cursor, mock_conn)
        )
        mock_get_cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_cursor.fetchall.return_value = [
            {"codigo": "4711", "descripcion": "VENTA AL POR MENOR"},
        ]

        from catalogs import lookup_actividad_comercial

        # lowercase input should still match
        assert lookup_actividad_comercial("venta al por menor") == "4711"
        assert lookup_actividad_comercial("  VENTA AL POR MENOR  ") == "4711"
        assert lookup_actividad_comercial("no existe") == ""

    def test_lookup_empty_descripcion(self):
        from catalogs import lookup_actividad_comercial

        assert lookup_actividad_comercial("") == ""

    @patch("catalogs.get_cursor")
    def test_catalog_cached(self, mock_get_cursor):
        """Verify catalog is loaded only once (cached)."""
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_get_cursor.return_value.__enter__ = MagicMock(
            return_value=(mock_cursor, mock_conn)
        )
        mock_get_cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = [{"codigo": "01", "descripcion": "TEST"}]

        from catalogs import get_actividad_comercial_catalog

        # Call twice
        get_actividad_comercial_catalog()
        get_actividad_comercial_catalog()

        # Should only query SQL once (cached after first call)
        assert mock_cursor.execute.call_count == 1
