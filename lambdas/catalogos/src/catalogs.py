"""Catalog data access — direct SQL Server queries.

Queries reference tables from NAV SQL Server using the shared db module.
Caches loaded catalogs in module-level dicts for warm Lambda reuse.
"""

from __future__ import annotations

import logging
from typing import Any

from db import get_cursor

logger = logging.getLogger(__name__)

# Module-level caches (survive across warm invocations)
_actividad_catalog: dict[str, str] | None = None

# SQL Server table for actividad económica (DGII reference, maintained by Kike)
TABLE_ACTIVIDAD_ECONOMICA = "[dbo].[COMERSAL$GLORY_ACTIVIDAD_ECONOMICA]"


def _load_actividad_catalog() -> dict[str, str]:
    """Load actividad económica catalog from SQL Server."""
    with get_cursor() as (cursor, _conn):
        cursor.execute(
            f"SELECT codigo, descripcion FROM {TABLE_ACTIVIDAD_ECONOMICA} "
            "WHERE disponible = 'Y'"
        )
        rows = cursor.fetchall()

    catalog: dict[str, str] = {}
    for row in rows:
        codigo = str(row.get("codigo", "")).strip()
        descripcion = str(row.get("descripcion", "")).strip().upper()
        if codigo and descripcion:
            catalog[descripcion] = codigo

    logger.info("Actividad comercial catalog loaded", extra={"entries": len(catalog)})
    return catalog


def get_actividad_comercial_catalog() -> dict[str, str]:
    """Get the cached catalog (description → code mapping)."""
    global _actividad_catalog
    if _actividad_catalog is None:
        _actividad_catalog = _load_actividad_catalog()
    return _actividad_catalog


def lookup_actividad_comercial(descripcion: str) -> str:
    """Lookup actividad económica description → código. Case-insensitive."""
    if not descripcion:
        return ""
    catalog = get_actividad_comercial_catalog()
    return catalog.get(descripcion.strip().upper(), "")
