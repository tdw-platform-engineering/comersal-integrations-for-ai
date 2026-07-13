"""Lambda handler — Query open invoices from NAV SQL Server.

Invoked synchronously. Supports two actions:
  - por_cliente: list invoices by client code
  - obtener: get a specific invoice by number

Input: {"action": "por_cliente", "cod_cte": "..."} or {"action": "obtener", "factura": "..."}
"""

from __future__ import annotations

import json
import logging
from typing import Any

from db import get_cursor
from models import VIEW_FACTURAS, FacturaAbierta

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Route to action handler."""
    body = event
    if "body" in event and isinstance(event["body"], str):
        body = json.loads(event["body"])

    action = body.get("action", "")

    if action == "por_cliente":
        return _por_cliente(body)
    elif action == "obtener":
        return _obtener(body)
    else:
        return {"ok": False, "errores": [f"Acción no reconocida: '{action}'"]}


def _por_cliente(body: dict) -> dict[str, Any]:
    cod_cte = str(body.get("cod_cte", "")).strip()
    if not cod_cte:
        return {"ok": False, "errores": ["cod_cte es requerido"]}

    pagina = int(body.get("pagina", 1))
    por_pagina = min(int(body.get("por_pagina", 50)), 200)
    offset = (pagina - 1) * por_pagina

    with get_cursor() as (cursor, _conn):
        cursor.execute(
            f"SELECT COUNT(*) AS total FROM {VIEW_FACTURAS} WHERE [Código cliente] = %s",
            (cod_cte,),
        )
        total = cursor.fetchone()["total"]

        cursor.execute(
            f"SELECT * FROM {VIEW_FACTURAS} WHERE [Código cliente] = %s "
            f"ORDER BY [Fecha factura] DESC OFFSET %s ROWS FETCH NEXT %s ROWS ONLY",
            (cod_cte, offset, por_pagina),
        )
        rows = [FacturaAbierta.from_row(r).to_dict() for r in cursor.fetchall()]

    return {"ok": True, "data": rows, "total": total, "pagina": pagina}


def _obtener(body: dict) -> dict[str, Any]:
    factura = str(body.get("factura", "")).strip()
    if not factura:
        return {"ok": False, "errores": ["factura es requerido"]}

    with get_cursor() as (cursor, _conn):
        cursor.execute(f"SELECT * FROM {VIEW_FACTURAS} WHERE [Factura] = %s", (factura,))
        row = cursor.fetchone()

    if not row:
        return {"ok": False, "errores": [f"Factura '{factura}' no encontrada"]}

    return {"ok": True, "data": FacturaAbierta.from_row(row).to_dict()}
