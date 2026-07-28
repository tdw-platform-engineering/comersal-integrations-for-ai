"""Lambda handler — Lookup reference catalogs from NAV SQL Server.

Serves small, rarely-changing reference catalogs:
  - actividad_comercial: REGCOM code lookup (for CFIS invoicing)

Invoked synchronously by Anima flush Lambda tools.

Input: {"action": "actividad_comercial", "descripcion": "..."} or
       {"action": "actividad_comercial_all"}
"""

from __future__ import annotations

import json
import logging
from typing import Any

from catalogs import lookup_actividad_comercial, get_actividad_comercial_catalog

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Route to catalog action handler."""
    body = event
    if "body" in event and isinstance(event["body"], str):
        body = json.loads(event["body"])

    action = body.get("action", "")

    if action == "actividad_comercial":
        return _actividad_comercial(body)
    elif action == "actividad_comercial_all":
        return _actividad_comercial_all()
    else:
        return {"ok": False, "errores": [f"Acción no reconocida: '{action}'"]}


def _actividad_comercial(body: dict) -> dict[str, Any]:
    """Lookup a single actividad económica description → REGCOM code."""
    descripcion = str(body.get("descripcion", "")).strip()
    if not descripcion:
        return {"ok": False, "errores": ["descripcion es requerido"]}

    codigo = lookup_actividad_comercial(descripcion)

    if codigo:
        return {"ok": True, "data": {"codigo": codigo, "descripcion": descripcion}}
    else:
        return {
            "ok": False,
            "errores": [f"Actividad económica no encontrada: '{descripcion}'"],
        }


def _actividad_comercial_all() -> dict[str, Any]:
    """Return the full actividad económica catalog (small — ~400 entries)."""
    catalog = get_actividad_comercial_catalog()
    return {"ok": True, "data": catalog, "total": len(catalog)}
