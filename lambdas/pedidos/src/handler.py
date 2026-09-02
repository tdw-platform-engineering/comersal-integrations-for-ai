"""Lambda handler — Create order in NAV SQL Server.

Invoked synchronously by Anima flush Lambda (confirmar_pedido tool).
Validates, generates NUMTRA, inserts header + detail rows.

Input: {"encabezado": {...}, "lineas": [...]}
Output: {"ok": true, "numtra": "PAWS-...", "mensaje": "..."} or {"ok": false, "errores": [...]}
"""

from __future__ import annotations

import json
import logging
from typing import Any

from numtra import get_next_numtra
from service import crear_pedido, ErrorValidacion

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Create or query an order. Returns result directly (synchronous invocation)."""
    request_id = getattr(context, "aws_request_id", "local") if context else "local"

    # Support both direct payload and API Gateway-style (body as string)
    body = event
    if "body" in event and isinstance(event["body"], str):
        body = json.loads(event["body"])

    # Route by action (default: crear)
    action = body.get("action", "crear")

    if action == "obtener":
        return _obtener_pedido(body)

    if action == "lista_precio":
        return _lista_precio(body)

    # --- crear flow ---
    encabezado = body.get("encabezado", {})
    lineas = body.get("lineas", [])

    if not lineas:
        return _error_response(["El pedido debe incluir al menos una línea de detalle."])

    logger.info(
        "Creating order",
        extra={
            "request_id": request_id,
            "cod_cte": encabezado.get("cod_cte"),
            "num_lineas": len(lineas),
        },
    )

    try:
        # Generate NUMTRA directly from SQL Server (no Athena)
        numtra = get_next_numtra()

        # Inject numtra into header
        encabezado["numtra"] = numtra

        # Validate and insert
        result = crear_pedido(encabezado, lineas)

        logger.info("Order created", extra={"numtra": numtra, "request_id": request_id})

        return {
            "ok": True,
            "numtra": numtra,
            "mensaje": f"Pedido {numtra} creado exitosamente con {len(lineas)} líneas.",
            "data": result,
        }

    except ErrorValidacion as e:
        logger.warning(
            "Validation failed",
            extra={"errores": e.errores, "request_id": request_id},
        )
        return _error_response(e.errores)

    except Exception as e:
        logger.exception("Unexpected error creating order", extra={"request_id": request_id})
        return _error_response([f"Error interno: {str(e)}"], status=500)


def _error_response(errores: list[str], status: int = 400) -> dict[str, Any]:
    return {"ok": False, "errores": errores, "status": status}


def _lista_precio(body: dict[str, Any]) -> dict[str, Any]:
    """Return a client's price list (ListaPrecio) from NAV View_AC_Clientes.

    Used by the Anima flush Lambda as a self-heal fallback when a registered
    client's DynamoDB profile is missing `priceList`: flush fetches the real
    list from NAV (source of truth), writes it back to the profile, and alarms.

    Input:  {"action": "lista_precio", "cod_cte": "1044086"}
    Output: {"ok": true, "cod_cte": "1044086", "lista_precio": "LP_AUTOMA"}
            or {"ok": false, "errores": [...]}
    """
    from db import get_cursor
    from models import VIEW_CLIENTES

    cod_cte = str(body.get("cod_cte", "")).strip()
    if not cod_cte:
        return _error_response(["cod_cte es requerido"])

    with get_cursor() as (cursor, _conn):
        cursor.execute(
            f"SELECT TOP 1 ListaPrecio FROM {VIEW_CLIENTES} WHERE CodCte = %s",
            (cod_cte,),
        )
        row = cursor.fetchone()

    if not row:
        return _error_response([f"Cliente '{cod_cte}' no encontrado"])

    # get_cursor(as_dict=True) → row is a dict keyed by column name.
    lista = str((row.get("ListaPrecio") if isinstance(row, dict) else row[0]) or "").strip()
    if not lista:
        return _error_response([f"Cliente '{cod_cte}' no tiene ListaPrecio en NAV"])

    return {"ok": True, "cod_cte": cod_cte, "lista_precio": lista}


def _obtener_pedido(body: dict[str, Any]) -> dict[str, Any]:
    """Read an order back from the DB by numtra."""
    from config import NAV_PEDIDO_ENC_TABLE, NAV_PEDIDO_DET_TABLE
    from db import get_cursor

    numtra = str(body.get("numtra", "")).strip()
    if not numtra:
        return _error_response(["numtra es requerido"])

    with get_cursor() as (cursor, _conn):
        cursor.execute(f"SELECT * FROM {NAV_PEDIDO_ENC_TABLE} WHERE NUMTRA = %s", (numtra,))
        enc = cursor.fetchone()
        if not enc:
            return _error_response([f"Pedido '{numtra}' no encontrado"])

        cursor.execute(
            f"SELECT * FROM {NAV_PEDIDO_DET_TABLE} WHERE NUMTRA = %s ORDER BY CODLIN",
            (numtra,),
        )
        detalles = cursor.fetchall()

    return {
        "ok": True,
        "data": {
            "numtra": str(enc.get("NUMTRA", "")),
            "cod_cte": str(enc.get("CODCTE", "")),
            "cod_ven": str(enc.get("CODVEN", "")),
            "val_tot": str(enc.get("VALTOT", 0)),
            "status": int(enc.get("STATUS", 0) or 0),
            "fecha": f"{enc.get('ANOSIS', 0)}-{int(enc.get('MESSIS', 0) or 0):02d}-{int(enc.get('DIASIS', 0) or 0):02d}",
            "num_lineas": len(detalles),
            "lineas": [
                {
                    "codlin": int(d.get("CODLIN", 0) or 0),
                    "cod_pro": str(d.get("CODPRO", "")),
                    "ped_caj": int(d.get("PEDCAJ", 0) or 0),
                    "ped_und": int(d.get("PEDUND", 0) or 0),
                }
                for d in detalles
            ],
        },
    }
