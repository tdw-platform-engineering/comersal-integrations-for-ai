"""Unit tests for the pedidos Lambda handler."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("SQLSERVER_CONNECTION_STRING", "mssql+pymssql://u:p@host:1433/db")


@pytest.fixture
def mock_db():
    with patch("src.service.get_cursor") as m:
        cursor = MagicMock()
        conn = MagicMock()
        m.return_value.__enter__ = MagicMock(return_value=(cursor, conn))
        m.return_value.__exit__ = MagicMock(return_value=False)
        yield cursor, conn


def test_empty_lineas():
    from src.handler import lambda_handler

    result = lambda_handler({"encabezado": {}, "lineas": []}, None)
    assert result["ok"] is False
    assert "al menos una línea" in result["errores"][0]


def test_missing_cod_cte():
    from src.handler import lambda_handler

    with patch("src.handler.get_next_numtra", return_value="PAWS-0000000001"):
        with patch("src.handler.crear_pedido") as mock_crear:
            from src.service import ErrorValidacion
            mock_crear.side_effect = ErrorValidacion(["cod_cte es requerido"])

            result = lambda_handler(
                {"encabezado": {"cod_ven": "V01"}, "lineas": [{"cod_pro": "X"}]},
                None,
            )
            assert result["ok"] is False
            assert "cod_cte" in result["errores"][0]


def test_success():
    from src.handler import lambda_handler

    with patch("src.handler.get_next_numtra", return_value="PAWS-0000000042"):
        with patch("src.handler.crear_pedido") as mock_crear:
            mock_crear.return_value = {"numtra": "PAWS-0000000042", "num_lineas": 1}

            result = lambda_handler(
                {
                    "encabezado": {"cod_cte": "100", "cod_ven": "V01"},
                    "lineas": [{"cod_pro": "P1", "ped_caj": 1, "fac_emp": 12, "val_cto": 5.0}],
                },
                None,
            )
            assert result["ok"] is True
            assert result["numtra"] == "PAWS-0000000042"
