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
from service import ErrorValidacion, crear_pedido

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

    if action == "diag_seq":
        return _diag_seq()

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


def _diag_seq() -> dict[str, Any]:
    """TEMPORARY read-only diagnostic — exhaustively hunt for seq_pedido_glory.

    Does NOT assume the object is a SQL Server SEQUENCE. Searches EVERY database
    on the NAV server (sys.databases) for ANY object named 'seq_pedido_glory'
    of ANY type (table/view/proc/function/sequence) via sys.objects, and if any
    match is a SEQUENCE, reads its current_value/increment/start. Read-only.
    Removed after Step-1 verification.
    """
    from config import NAV_NUMTRA_SEQUENCE
    from db import get_cursor

    # Bare object name to hunt for (strip any schema qualifier).
    parts = NAV_NUMTRA_SEQUENCE.split(".")
    target_name = parts[1] if len(parts) == 2 else parts[0]

    # Map sys.objects.type to a human label.
    type_labels = {
        "U": "USER_TABLE",
        "V": "VIEW",
        "SO": "SEQUENCE",
        "P": "SQL_STORED_PROCEDURE",
        "FN": "SCALAR_FUNCTION",
        "IF": "INLINE_TABLE_FUNCTION",
        "TF": "TABLE_FUNCTION",
        "SN": "SYNONYM",
    }

    matches: list[dict[str, Any]] = []
    all_sequences: list[dict[str, Any]] = []
    databases: list[str] = []
    errors: list[str] = []
    identity: dict[str, Any] = {}
    access_probe: list[dict[str, Any]] = []

    with get_cursor() as (cursor, _conn):
        cursor.execute("SELECT DB_NAME() AS db, @@SERVERNAME AS server")
        ctx = cursor.fetchone() or {}
        current_db = str(ctx.get("db", ""))
        server_name = str(ctx.get("server", ""))

        # Connection identity + server-level role membership. Answers "who am I
        # and could a missing GRANT be hiding the object from me?".
        cursor.execute(
            """
            SELECT SUSER_SNAME()                              AS login_name,
                   USER_NAME()                                AS db_user,
                   IS_SRVROLEMEMBER('sysadmin')               AS is_sysadmin,
                   IS_MEMBER('db_owner')                      AS is_db_owner,
                   IS_MEMBER('db_datareader')                 AS is_db_datareader
            """
        )
        idrow = cursor.fetchone() or {}
        identity = {
            "login_name": str(idrow.get("login_name", "")),
            "db_user": str(idrow.get("db_user", "")),
            "is_sysadmin": bool(idrow.get("is_sysadmin")),
            "is_db_owner": bool(idrow.get("is_db_owner")),
            "is_db_datareader": bool(idrow.get("is_db_datareader")),
        }

        # Can this login run NEXT VALUE FOR the sequence? That requires the
        # UPDATE permission on the SEQUENCE object. HAS_PERMS_BY_NAME checks it
        # WITHOUT consuming the sequence (read-only) — returns 1/0, or NULL if the
        # object can't be resolved. Checked against the fully-qualified name in
        # the CURRENT db context.
        seq_perm: dict[str, Any] = {}
        try:
            cursor.execute(
                """
                SELECT HAS_PERMS_BY_NAME(%s, 'OBJECT', 'UPDATE') AS can_update,
                       HAS_PERMS_BY_NAME(%s, 'OBJECT', 'SELECT') AS can_select,
                       HAS_PERMS_BY_NAME(%s, 'OBJECT', 'REFERENCES') AS can_reference
                """,
                (NAV_NUMTRA_SEQUENCE, NAV_NUMTRA_SEQUENCE, NAV_NUMTRA_SEQUENCE),
            )
            prow = cursor.fetchone() or {}
            seq_perm = {
                "object": NAV_NUMTRA_SEQUENCE,
                "can_update_next_value_for": (
                    None if prow.get("can_update") is None else bool(prow.get("can_update"))
                ),
                "can_select": (
                    None if prow.get("can_select") is None else bool(prow.get("can_select"))
                ),
                "can_reference": (
                    None if prow.get("can_reference") is None else bool(prow.get("can_reference"))
                ),
            }
        except Exception as e:  # noqa: BLE001
            seq_perm = {"object": NAV_NUMTRA_SEQUENCE, "error": str(e)}

        # All online, readable databases on this server.
        cursor.execute(
            """
            SELECT name FROM sys.databases
            WHERE state = 0
              AND HAS_DBACCESS(name) = 1
            ORDER BY name
            """
        )
        databases = [str(r.get("name", "")) for r in (cursor.fetchall() or [])]

        # Hunt the object name in each database via a 3-part sys.objects query.
        for db in databases:
            safe_db = db.replace("]", "]]")  # bracket-escape only; name is from catalog
            try:
                # Broaden: match the exact name OR any name CONTAINING the key
                # tokens (covers company-prefixed / GUID-suffixed NAV names like
                # 'PRUEBAS_NAV$seq_pedido_glory$<guid>', different schema, etc.).
                # Use CHARINDEX (not LIKE) to avoid '%' colliding with pymssql's
                # parameter placeholders.
                cursor.execute(
                    f"""
                    SELECT DB_NAME(DB_ID(%s)) AS db_name,
                           SCHEMA_NAME(o.schema_id) AS obj_schema,
                           o.name AS obj_name,
                           o.type AS obj_type
                    FROM [{safe_db}].sys.objects o
                    WHERE o.name = %s
                       OR CHARINDEX('pedido_glory', LOWER(o.name)) > 0
                       OR CHARINDEX('seq_pedido', LOWER(o.name)) > 0
                       OR CHARINDEX('glory', LOWER(o.name)) > 0
                    """,
                    (db, target_name),
                )
                for r in cursor.fetchall() or []:
                    otype = str(r.get("obj_type", "")).strip()
                    entry: dict[str, Any] = {
                        "database": str(r.get("db_name", db)),
                        "schema": str(r.get("obj_schema", "")),
                        "name": str(r.get("obj_name", "")),
                        "type": otype,
                        "type_label": type_labels.get(otype, otype),
                    }
                    # If it's a SEQUENCE, pull its details from that DB.
                    if otype == "SO":
                        cursor.execute(
                            f"""
                            SELECT CAST(current_value AS BIGINT) AS current_value,
                                   CAST(increment AS BIGINT)      AS increment,
                                   CAST(start_value AS BIGINT)    AS start_value,
                                   TYPE_NAME(system_type_id)      AS data_type,
                                   is_exhausted
                            FROM [{safe_db}].sys.sequences
                            WHERE name = %s AND SCHEMA_NAME(schema_id) = %s
                            """,
                            (r.get("obj_name"), r.get("obj_schema")),
                        )
                        sd = cursor.fetchone() or {}
                        entry["sequence_detail"] = {
                            "current_value": int(sd["current_value"])
                            if sd.get("current_value") is not None
                            else None,
                            "increment": int(sd["increment"])
                            if sd.get("increment") is not None
                            else None,
                            "start_value": int(sd["start_value"])
                            if sd.get("start_value") is not None
                            else None,
                            "data_type": str(sd.get("data_type", "")),
                            "is_exhausted": bool(sd.get("is_exhausted")),
                        }
                    matches.append(entry)

                # Also list EVERY sequence in this DB (any name/schema) — so a
                # sequence created under a different name is still surfaced.
                cursor.execute(
                    f"""
                    SELECT SCHEMA_NAME(schema_id) AS seq_schema,
                           name                    AS seq_name,
                           CAST(current_value AS BIGINT) AS current_value,
                           CAST(increment AS BIGINT)     AS increment
                    FROM [{safe_db}].sys.sequences
                    ORDER BY seq_schema, seq_name
                    """
                )
                for s in cursor.fetchall() or []:
                    all_sequences.append(
                        {
                            "database": db,
                            "schema": str(s.get("seq_schema", "")),
                            "name": str(s.get("seq_name", "")),
                            "current_value": int(s["current_value"])
                            if s.get("current_value") is not None
                            else None,
                            "increment": int(s["increment"])
                            if s.get("increment") is not None
                            else None,
                        }
                    )
            except Exception as e:  # noqa: BLE001 — record per-DB access errors
                errors.append(f"{db}: {e}")

        # Definitive existence-vs-permission probe per DB. describe_first_result_set
        # PARSES + BINDS the statement (resolves the object + checks permissions)
        # WITHOUT executing it — so it never consumes the sequence. On failure it
        # returns error_number/error_message as columns:
        #   - 208 "Invalid object name"      → the object truly does NOT exist.
        #   - 229/300/others "permission ..." → object EXISTS but GRANT is missing.
        # NULL error columns → the object exists and is usable by this login.
        for db in databases:
            safe_db = db.replace("]", "]]")
            # dbo-qualified target; object name comes from config, not user input.
            stmt = f"SELECT NEXT VALUE FOR dbo.{target_name}".replace("'", "''")
            try:
                cursor.execute(
                    f"""
                    USE [{safe_db}];
                    SELECT error_number, error_message
                    FROM sys.dm_exec_describe_first_result_set(N'{stmt}', NULL, 0)
                    """
                )
                prow = cursor.fetchone() or {}
                err_no = prow.get("error_number")
                err_msg = prow.get("error_message")
                if err_no is None:
                    verdict = "usable"  # exists + this login can use it
                elif int(err_no) == 208:
                    verdict = "not_found"  # invalid object name → doesn't exist
                else:
                    verdict = "permission_or_other"  # exists but blocked / other
                access_probe.append(
                    {
                        "database": db,
                        "verdict": verdict,
                        "error_number": int(err_no) if err_no is not None else None,
                        "error_message": str(err_msg) if err_msg is not None else None,
                    }
                )
            except Exception as e:  # noqa: BLE001
                access_probe.append(
                    {"database": db, "verdict": "probe_error", "error_message": str(e)}
                )

        # Inspect the ENC table columns — rule out a "sequence-like" column
        # living INSIDE the header table (identity, or a column whose DEFAULT
        # consumes NEXT VALUE FOR a sequence). Also surfaces the exact column
        # structure so we can confirm where NUMTRA lives.
        from config import NAV_PEDIDO_ENC_TABLE

        enc_columns: list[dict[str, Any]] = []
        enc_error = None
        enc_context_db = None
        enc_object_id = None
        try:
            # Restore the DB context: the access_probe loop ran `USE [db]` and
            # left the connection pointed at the LAST scanned DB (e.g. tempdb),
            # where the ENC table does not exist. Point back at the original DB
            # so OBJECT_ID resolves the ENC table correctly.
            safe_current = current_db.replace("]", "]]")
            if safe_current:
                cursor.execute(f"USE [{safe_current}]")
            # Confirm context + whether the ENC table resolves at all.
            cursor.execute(
                "SELECT DB_NAME() AS db, OBJECT_ID(%s) AS oid", (NAV_PEDIDO_ENC_TABLE,)
            )
            _ctx = cursor.fetchone() or {}
            enc_context_db = str(_ctx.get("db", ""))
            enc_object_id = _ctx.get("oid")
            cursor.execute(
                """
                SELECT c.name                          AS column_name,
                       TYPE_NAME(c.user_type_id)        AS data_type,
                       c.max_length                     AS max_length,
                       c.is_identity                    AS is_identity,
                       c.is_computed                    AS is_computed,
                       dc.definition                    AS default_definition
                FROM sys.columns c
                LEFT JOIN sys.default_constraints dc
                       ON dc.parent_object_id = c.object_id
                      AND dc.parent_column_id = c.column_id
                WHERE c.object_id = OBJECT_ID(%s)
                ORDER BY c.column_id
                """,
                (NAV_PEDIDO_ENC_TABLE,),
            )
            for r in cursor.fetchall() or []:
                default_def = r.get("default_definition")
                enc_columns.append(
                    {
                        "column": str(r.get("column_name", "")),
                        "type": str(r.get("data_type", "")),
                        "is_identity": bool(r.get("is_identity")),
                        "is_computed": bool(r.get("is_computed")),
                        "default": str(default_def) if default_def is not None else None,
                        # Flag columns whose DEFAULT consumes a sequence.
                        "uses_next_value_for": bool(
                            default_def and "NEXT VALUE FOR" in str(default_def).upper()
                        ),
                    }
                )
        except Exception as e:  # noqa: BLE001
            enc_error = str(e)
            enc_context_db = None
            enc_object_id = None

    return {
        "ok": True,
        "server": server_name,
        "current_db": current_db,
        "target_name": target_name,
        "identity": identity,
        "sequence_permissions": seq_perm,
        "databases_scanned": databases,
        "matches": matches,
        "match_count": len(matches),
        "all_sequences": all_sequences,
        "all_sequences_count": len(all_sequences),
        "access_probe": access_probe,
        "enc_table": NAV_PEDIDO_ENC_TABLE,
        "enc_context_db": enc_context_db,
        "enc_object_id": int(enc_object_id) if enc_object_id is not None else None,
        "enc_columns": enc_columns,
        "enc_columns_error": enc_error,
        "scan_errors": errors,
    }


def _obtener_pedido(body: dict[str, Any]) -> dict[str, Any]:
    """Read an order back from the DB by numtra."""
    from config import NAV_PEDIDO_DET_TABLE, NAV_PEDIDO_ENC_TABLE
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
