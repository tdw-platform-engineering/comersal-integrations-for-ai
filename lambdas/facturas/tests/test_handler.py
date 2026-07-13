"""Unit tests for facturas Lambda handler."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("SQLSERVER_CONNECTION_STRING", "mssql+pymssql://u:p@host:1433/db")


def test_unknown_action():
    from src.handler import lambda_handler

    result = lambda_handler({"action": "nope"}, None)
    assert result["ok"] is False


def test_por_cliente_missing_cod_cte():
    from src.handler import lambda_handler

    result = lambda_handler({"action": "por_cliente"}, None)
    assert result["ok"] is False
    assert "cod_cte" in result["errores"][0]


def test_obtener_missing_factura():
    from src.handler import lambda_handler

    result = lambda_handler({"action": "obtener"}, None)
    assert result["ok"] is False
    assert "factura" in result["errores"][0]
