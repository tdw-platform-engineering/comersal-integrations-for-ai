"""Unit tests for catalogos Lambda handler."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("SQLSERVER_CONNECTION_STRING", "mssql+pymssql://u:p@host:1433/db")


class TestRouting:
    def test_unknown_action(self):
        from handler import lambda_handler

        result = lambda_handler({"action": "nope"}, None)
        assert result["ok"] is False
        assert "no reconocida" in result["errores"][0]

    def test_body_as_string(self):
        """Handles API Gateway-style body-as-string payloads."""
        import json
        from handler import lambda_handler

        result = lambda_handler({"body": json.dumps({"action": "invalid"})}, None)
        assert result["ok"] is False


class TestActividadComercial:
    def test_missing_descripcion(self):
        from handler import lambda_handler

        result = lambda_handler({"action": "actividad_comercial"}, None)
        assert result["ok"] is False
        assert "descripcion" in result["errores"][0]

    def test_empty_descripcion(self):
        from handler import lambda_handler

        result = lambda_handler({"action": "actividad_comercial", "descripcion": "  "}, None)
        assert result["ok"] is False

    @patch("handler.lookup_actividad_comercial")
    def test_found(self, mock_lookup):
        mock_lookup.return_value = "4711"
        from handler import lambda_handler

        result = lambda_handler(
            {"action": "actividad_comercial", "descripcion": "VENTA DE ALIMENTOS"},
            None,
        )
        assert result["ok"] is True
        assert result["data"]["codigo"] == "4711"

    @patch("handler.lookup_actividad_comercial")
    def test_not_found(self, mock_lookup):
        mock_lookup.return_value = ""
        from handler import lambda_handler

        result = lambda_handler(
            {"action": "actividad_comercial", "descripcion": "NO EXISTE"},
            None,
        )
        assert result["ok"] is False
        assert "no encontrada" in result["errores"][0]

    @patch("handler.get_actividad_comercial_catalog")
    def test_all(self, mock_catalog):
        mock_catalog.return_value = {"VENTA": "01", "COMPRA": "02"}
        from handler import lambda_handler

        result = lambda_handler({"action": "actividad_comercial_all"}, None)
        assert result["ok"] is True
        assert result["total"] == 2
