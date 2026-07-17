"""Order creation service — validate + insert into NAV tables.

Combines header construction, detail lines, validations (stock, prices,
client existence), and the actual DB writes.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from db import get_cursor
from models import (
    TABLE_PEDIDO_ENC,
    TABLE_PEDIDO_DET,
    VIEW_CLIENTES,
    VIEW_EXISTENCIA,
    VIEW_PRODUCTOS,
    PedidoDetalle,
    PedidoEncabezado,
)

logger = logging.getLogger(__name__)


class ErrorValidacion(ValueError):
    """Validation error with list of specific issues."""

    def __init__(self, errores: list[str]):
        self.errores = errores
        super().__init__("; ".join(errores))


def crear_pedido(datos_enc: dict[str, Any], lineas: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate and insert a complete order (header + lines).

    Args:
        datos_enc: Header fields (numtra, cod_cte, cod_ven, totals).
        lineas: List of line item dicts.

    Returns:
        Dict with numtra and summary.

    Raises:
        ErrorValidacion: If business validations fail.
    """
    enc = PedidoEncabezado(
        numtra=str(datos_enc.get("numtra", "")),
        cod_cte=str(datos_enc.get("cod_cte", "")),
        cod_ven=str(datos_enc.get("cod_ven", "")),
        val_gra=Decimal(str(datos_enc.get("val_gra", 0))),
        val_iva=Decimal(str(datos_enc.get("val_iva", 0))),
        val_tot=Decimal(str(datos_enc.get("val_tot", 0))),
        obser1=str(datos_enc.get("obser1", "")),
        obser2=str(datos_enc.get("obser2", "")),
        comentario=str(datos_enc.get("comentario", "")),
        cod_pag=str(datos_enc.get("cod_pag", "")),
        cod_rut=str(datos_enc.get("cod_rut", "")),
        celular=str(datos_enc.get("celular", "")),
        departamento=str(datos_enc.get("departamento", "")),
        municipio=str(datos_enc.get("municipio", "")),
    )
    enc.validar()
    enc.auto_llenar()

    detalles: list[PedidoDetalle] = []
    for i, ld in enumerate(lineas, 1):
        det = PedidoDetalle(
            cod_pro=str(ld.get("cod_pro", "")),
            ped_caj=int(ld.get("ped_caj", 0)),
            ped_und=int(ld.get("ped_und", 0)),
            fac_emp=int(ld.get("fac_emp", 0)),
            val_cto=Decimal(str(ld.get("val_cto", 0))),
            val_vtc=Decimal(str(ld.get("val_vtc", 0))),
            val_vts=Decimal(str(ld.get("val_vts", 0))),
            val_esc=Decimal(str(ld.get("val_esc", 0))),
            numtra=enc.numtra,
            codlin=i,
            num_ped=enc.numtra,
            cod_cte=enc.cod_cte,
            cod_ven=enc.cod_ven,
            ano_sis=enc.ano_sis,
            mes_sis=enc.mes_sis,
            dia_sis=enc.dia_sis,
            hor_sis=enc.hor_sis,
        )
        det.validar()
        detalles.append(det)

    # Business validations against DB
    _validar_pedido(enc, detalles)

    # Insert
    _insertar_pedido(enc, detalles)

    return {
        "numtra": enc.numtra,
        "cod_cte": enc.cod_cte,
        "num_lineas": len(detalles),
        "val_tot": str(enc.val_tot),
    }


def _validar_pedido(enc: PedidoEncabezado, detalles: list[PedidoDetalle]) -> None:
    """Run business validations against the DB. Raises ErrorValidacion."""
    errores: list[str] = []

    with get_cursor() as (cursor, _conn):
        # 1. Client exists
        cursor.execute(f"SELECT TOP 1 CodCte FROM {VIEW_CLIENTES} WHERE CodCte = %s", (enc.cod_cte,))
        if cursor.fetchone() is None:
            errores.append(f"El cliente '{enc.cod_cte}' no existe en el sistema")

        # 2. Duplicate numtra
        cursor.execute(f"SELECT TOP 1 NUMTRA FROM {TABLE_PEDIDO_ENC} WHERE NUMTRA = %s", (enc.numtra,))
        if cursor.fetchone() is not None:
            errores.append(f"Ya existe un pedido con número '{enc.numtra}'")

        # 3. Per-line validations
        codigos_vistos: set[str] = set()
        for det in detalles:
            linea = f"Línea {det.codlin} ({det.cod_pro})"

            if det.cod_pro in codigos_vistos:
                errores.append(f"{linea}: producto duplicado")
            codigos_vistos.add(det.cod_pro)

            # Product exists + fac_empaque check
            cursor.execute(
                f"SELECT CodPro, FacEmpaque FROM {VIEW_PRODUCTOS} WHERE CodPro = %s",
                (det.cod_pro,),
            )
            prod = cursor.fetchone()
            if prod is None:
                errores.append(f"{linea}: producto no existe")
                continue

            cat_fac = int(Decimal(str(prod.get("FacEmpaque", 0) or 0)))
            if det.fac_emp > 0 and cat_fac > 0 and det.fac_emp != cat_fac:
                errores.append(
                    f"{linea}: factor empaque ({det.fac_emp}) no coincide con catálogo ({cat_fac})"
                )

            # Stock check
            cursor.execute(
                f"SELECT COALESCE(SUM(TotalUnidades), 0) AS disp FROM {VIEW_EXISTENCIA} WHERE CodPro = %s",
                (det.cod_pro,),
            )
            stock_row = cursor.fetchone()
            disponible = int(Decimal(str(stock_row["disp"]))) if stock_row else 0
            pedido_unidades = det.ped_und + (det.ped_caj * max(det.fac_emp, 1))
            if disponible <= 0:
                errores.append(f"{linea}: sin existencia disponible")
            elif pedido_unidades > disponible:
                errores.append(f"{linea}: pedido ({pedido_unidades}) > existencia ({disponible})")

            # Price positive
            if det.val_cto <= 0:
                errores.append(f"{linea}: val_cto debe ser > 0")

    # Total coherence
    if detalles and enc.val_tot > 0:
        suma = sum(d.val_vtc for d in detalles)
        if suma > 0:
            diff = abs(enc.val_tot - suma)
            tol = Decimal("0.05") * len(detalles)
            if diff > tol:
                errores.append(f"Total ({enc.val_tot}) ≠ suma líneas ({suma}), diff={diff}")

    if errores:
        raise ErrorValidacion(errores)


def _insertar_pedido(enc: PedidoEncabezado, detalles: list[PedidoDetalle]) -> None:
    """Insert header + detail rows in a single transaction."""
    with get_cursor() as (cursor, conn):
        # Header
        row = enc.to_row()
        cols = list(row.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        cursor.execute(
            f"INSERT INTO {TABLE_PEDIDO_ENC} ({', '.join(cols)}) VALUES ({placeholders})",
            tuple(row.values()),
        )

        # Detail lines
        for det in detalles:
            row = det.to_row()
            cols = list(row.keys())
            placeholders = ", ".join(["%s"] * len(cols))
            cursor.execute(
                f"INSERT INTO {TABLE_PEDIDO_DET} ({', '.join(cols)}) VALUES ({placeholders})",
                tuple(row.values()),
            )

        conn.commit()

    logger.info("Order inserted: %s (%d lines)", enc.numtra, len(detalles))
