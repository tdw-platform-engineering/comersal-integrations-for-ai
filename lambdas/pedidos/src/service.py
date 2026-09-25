"""Order creation service — validate + insert into NAV tables.

Combines header construction, detail lines, validations (prices,
client existence), and the actual DB writes.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

from config import NAV_INSERT_TIMEOUT_SECONDS, NAV_PEDIDO_DET_TABLE, NAV_PEDIDO_ENC_TABLE
from db import get_cursor
from models import (
    VIEW_CLIENTES,
    VIEW_PRODUCTOS,
    PedidoDetalle,
    PedidoEncabezado,
)
from numtra import next_numtra

logger = logging.getLogger(__name__)


def _ms(start: float) -> float:
    """Elapsed milliseconds since ``start`` (from ``time.monotonic()``)."""
    return round((time.monotonic() - start) * 1000, 1)


class ErrorValidacion(ValueError):
    """Validation error with list of specific issues."""

    def __init__(self, errores: list[str]):
        self.errores = errores
        super().__init__("; ".join(errores))


class ErrorInsercion(RuntimeError):
    """Raised when the order-insert transaction fails or times out.

    Distinct from ErrorValidacion (business rules) — this is a DB/infra failure
    (e.g. the NAV insert exceeded NAV_INSERT_TIMEOUT_SECONDS and was interrupted).
    """


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
    # NUMTRA is assigned inside _insertar_pedido via NEXT VALUE FOR, in the same
    # transaction as the insert. Use a placeholder so construction/validation
    # (which require a non-empty numtra) pass; it is overwritten before insert.
    t0 = time.monotonic()
    logger.info(
        "crear_pedido: start (cod_cte=%s, num_lineas=%d)",
        datos_enc.get("cod_cte"),
        len(lineas),
    )
    enc = PedidoEncabezado(
        numtra=str(datos_enc.get("numtra", "")) or "PENDING",
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
        por_com=str(datos_enc.get("por_com", "")),
        reg_com=str(datos_enc.get("reg_com", "")),
        cod_tpo=str(datos_enc.get("cod_tpo", "")),
        cod_zon=str(datos_enc.get("cod_zon", "")),
    )
    enc.validar()
    enc.auto_llenar()
    logger.info("crear_pedido: header built + validated (%sms)", _ms(t0))

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
    logger.info("crear_pedido: %d detail lines built + validated (%sms)", len(detalles), _ms(t0))

    # Business validations against DB
    t_val = time.monotonic()
    _validar_pedido(enc, detalles)
    logger.info("crear_pedido: DB validations passed (%sms, total %sms)", _ms(t_val), _ms(t0))

    # Insert (generates the NUMTRA from the sequence inside the transaction)
    t_ins = time.monotonic()
    numtra = _insertar_pedido(enc, detalles)
    logger.info(
        "crear_pedido: insert complete numtra=%s (%sms, total %sms)",
        numtra,
        _ms(t_ins),
        _ms(t0),
    )

    return {
        "numtra": numtra,
        "cod_cte": enc.cod_cte,
        "num_lineas": len(detalles),
        "val_tot": str(enc.val_tot),
    }


def _validar_pedido(enc: PedidoEncabezado, detalles: list[PedidoDetalle]) -> None:
    """Run business validations against the DB. Raises ErrorValidacion."""
    errores: list[str] = []

    t_conn = time.monotonic()
    logger.info("_validar_pedido: opening DB connection for validations...")
    with get_cursor() as (cursor, _conn):
        logger.info("_validar_pedido: connection acquired (%sms)", _ms(t_conn))
        # 1. Client exists (skip for generic new-client code)
        if enc.cod_cte != "99999999":
            t_q = time.monotonic()
            cursor.execute(f"SELECT TOP 1 CodCte FROM {VIEW_CLIENTES} WHERE CodCte = %s", (enc.cod_cte,))
            if cursor.fetchone() is None:
                errores.append(f"El cliente '{enc.cod_cte}' no existe en el sistema")
            logger.info("_validar_pedido: client-exists check done (%sms)", _ms(t_q))

        # NOTE: no duplicate-NUMTRA check — the NUMTRA is now generated by the
        # dbo.seq_pedidos_glory SEQUENCE inside _insertar_pedido (NEXT VALUE FOR
        # is atomic and monotonic), so a collision cannot occur and the numtra
        # here is still the "PENDING" placeholder.

        # 3. Per-line validations
        t_lines = time.monotonic()
        codigos_vistos: set[str] = set()
        for det in detalles:
            linea = f"Línea {det.codlin} ({det.cod_pro})"

            if det.cod_pro in codigos_vistos:
                errores.append(f"{linea}: producto duplicado")
            codigos_vistos.add(det.cod_pro)

            # Product exists + fac_empaque check
            t_prod = time.monotonic()
            cursor.execute(
                f"SELECT CodPro, FacEmpaque FROM {VIEW_PRODUCTOS} WHERE CodPro = %s",
                (det.cod_pro,),
            )
            prod = cursor.fetchone()
            logger.info(
                "_validar_pedido: line %d product lookup %s (%sms)",
                det.codlin,
                det.cod_pro,
                _ms(t_prod),
            )
            if prod is None:
                errores.append(f"{linea}: producto no existe")
                continue

            cat_fac = int(Decimal(str(prod.get("FacEmpaque", 0) or 0)))
            if det.fac_emp > 0 and cat_fac > 0 and det.fac_emp != cat_fac:
                errores.append(
                    f"{linea}: factor empaque ({det.fac_emp}) no coincide con catálogo ({cat_fac})"
                )

            # Nota: la validación de stock se removió a propósito. Los productos
            # entran al pedido sin importar existencia disponible.

            # Price positive
            if det.val_cto <= 0:
                errores.append(f"{linea}: val_cto debe ser > 0")
        logger.info(
            "_validar_pedido: all %d line lookups done (%sms)", len(detalles), _ms(t_lines)
        )

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


def _insertar_pedido(enc: PedidoEncabezado, detalles: list[PedidoDetalle]) -> str:
    """Generate the NUMTRA and insert header + detail rows in ONE transaction.

    The correlativo is advanced by consuming dbo.seq_pedidos_glory
    (NEXT VALUE FOR) on the SAME cursor/transaction as the inserts, so advancing
    the sequence and persisting the order commit together. Returns the NUMTRA.
    """
    t_conn = time.monotonic()
    logger.info(
        "_insertar_pedido: opening DB connection for insert transaction (query_timeout=%ss)...",
        NAV_INSERT_TIMEOUT_SECONDS,
    )
    # A tight query_timeout means any single INSERT/sequence read that hangs
    # longer than NAV_INSERT_TIMEOUT_SECONDS is interrupted by pymssql
    # (OperationalError) instead of eating the whole 30s Lambda wall.
    with get_cursor(query_timeout=NAV_INSERT_TIMEOUT_SECONDS) as (cursor, conn):
        logger.info("_insertar_pedido: connection acquired (%sms)", _ms(t_conn))
        step = "init"
        try:
            # 1. Advance the correlativo (atomic) and assign it to header + lines.
            step = "next_numtra (sequence)"
            t_seq = time.monotonic()
            numtra = next_numtra(cursor)
            logger.info("_insertar_pedido: NUMTRA=%s from sequence (%sms)", numtra, _ms(t_seq))
            enc.numtra = numtra
            for det in detalles:
                det.numtra = numtra
                det.num_ped = numtra

            # 2. Header
            step = "header INSERT"
            t_hdr = time.monotonic()
            row = enc.to_row()
            cols = list(row.keys())
            col_sql = ", ".join(f"[{c}]" for c in cols)
            placeholders = ", ".join(["%s"] * len(cols))
            cursor.execute(
                f"INSERT INTO {NAV_PEDIDO_ENC_TABLE} ({col_sql}) VALUES ({placeholders})",
                tuple(row.values()),
            )
            logger.info(
                "_insertar_pedido: header INSERT done numtra=%s (%sms)", numtra, _ms(t_hdr)
            )

            # Detail lines
            t_lines = time.monotonic()
            for det in detalles:
                step = f"line {det.codlin} INSERT (cod_pro={det.cod_pro})"
                t_line = time.monotonic()
                row = det.to_row()
                cols = list(row.keys())
                col_sql = ", ".join(f"[{c}]" for c in cols)
                placeholders = ", ".join(["%s"] * len(cols))
                cursor.execute(
                    f"INSERT INTO {NAV_PEDIDO_DET_TABLE} ({col_sql}) VALUES ({placeholders})",
                    tuple(row.values()),
                )
                logger.info(
                    "_insertar_pedido: line %d/%d INSERT done cod_pro=%s (%sms)",
                    det.codlin,
                    len(detalles),
                    det.cod_pro,
                    _ms(t_line),
                )
            logger.info(
                "_insertar_pedido: all %d line INSERTs done (%sms), committing...",
                len(detalles),
                _ms(t_lines),
            )

            step = "commit"
            t_commit = time.monotonic()
            conn.commit()
            logger.info("_insertar_pedido: COMMIT done (%sms)", _ms(t_commit))
        except Exception as e:
            # Timeout (pymssql OperationalError) or any other DB failure: roll
            # back the partial transaction, log WHICH step died + how long it
            # ran, and raise a typed error so the handler ends with an error.
            elapsed = _ms(t_conn)
            logger.exception(
                "_insertar_pedido: FAILED at step '%s' after %sms "
                "(timeout=%ss) — rolling back partial order",
                step,
                elapsed,
                NAV_INSERT_TIMEOUT_SECONDS,
            )
            try:
                conn.rollback()
                logger.info("_insertar_pedido: rollback done")
            except Exception:
                logger.exception("_insertar_pedido: rollback ALSO failed")
            raise ErrorInsercion(
                f"Fallo al insertar el pedido en '{step}' tras {elapsed}ms "
                f"(timeout {NAV_INSERT_TIMEOUT_SECONDS}s): {e}"
            ) from e

    logger.info("Order inserted: %s (%d lines)", enc.numtra, len(detalles))
    return numtra
