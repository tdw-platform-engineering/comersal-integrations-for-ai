"""Domain models shared across lambdas — extracted from comersal-api-services-connect."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


# ═══════════════════════════════════════════════════════════════════════════════
# PEDIDOS
# ═══════════════════════════════════════════════════════════════════════════════

TABLE_PEDIDO_ENC = "[PRUEBAS_NAV$T_PEDIDO_ENC$326a852b-0bdf-4d79-816d-c14d4187f50c]"
TABLE_PEDIDO_DET = "[PRUEBAS_NAV$T_PEDIDO_DET$326a852b-0bdf-4d79-816d-c14d4187f50c]"


@dataclass
class PedidoEncabezado:
    """Order header — variable fields from consumer + auto-fill logic."""

    numtra: str = ""
    cod_cte: str = ""
    cod_ven: str = ""
    val_gra: Decimal = field(default_factory=lambda: Decimal("0"))
    val_iva: Decimal = field(default_factory=lambda: Decimal("0"))
    val_tot: Decimal = field(default_factory=lambda: Decimal("0"))
    obser1: str = ""  # Nombre Cliente
    obser2: str = ""
    comentario: str = ""  # Dirección
    cod_pag: str = ""  # Tipo Documento (FACT)
    cod_rut: str = ""  # Número de DUI
    celular: str = ""  # Número Celular del que escribe el cliente
    departamento: str = ""  # Departamento
    municipio: str = ""  # Municipio
    reg_com: str = ""  # Código Actividad Económica (crédito fiscal)
    status: int = 0
    ano_sis: int = 0
    mes_sis: int = 0
    dia_sis: int = 0
    hor_sis: str = ""
    ano_entg: int = 0
    mes_entg: int = 0
    dia_entg: int = 0

    def auto_llenar(self) -> None:
        now = datetime.now()
        if not self.ano_sis:
            self.ano_sis = now.year
        if not self.mes_sis:
            self.mes_sis = now.month
        if not self.dia_sis:
            self.dia_sis = now.day
        if not self.hor_sis:
            self.hor_sis = now.strftime("%H:%M:%S")
        if not self.ano_entg:
            self.ano_entg = self.ano_sis
        if not self.mes_entg:
            self.mes_entg = self.mes_sis
        if not self.dia_entg:
            self.dia_entg = self.dia_sis

    def to_row(self) -> dict:
        self.auto_llenar()
        return {
            "NUMTRA": self.numtra,
            "ANOENTG": self.ano_entg, "ANOSIS": self.ano_sis,
            "CANCOP": 0, "CODCTE": self.cod_cte, "CODDEP": 0,
            "CODFAC": 1, "CODFAM": 3, "CODIDE": self.cod_ven,
            "CONLIN": self.departamento, "CODLUG": self.municipio,
            "CODMUN": 0, "CODPAG": self.cod_pag,
            "CODRUT": self.cod_rut, "CODTPO": 0, "CODVEN": self.cod_ven,
            "CODZON": 0, "DIAETG": self.dia_entg, "DIASIS": self.dia_sis,
            "FLGACT": 0, "FLGGPF": 5, "HORSIS": self.hor_sis,
            "MESETG": self.mes_entg, "MESSIS": self.mes_sis,
            "NOMUSR": self.celular, "NUMGPO": 0, "NUMPED": self.numtra,
            "PORCOM": 0, "REGCOM": self.reg_com, "TASIVA": 0, "VALEXE": 0,
            "VALGRA": self.val_gra, "VALIVA": self.val_iva,
            "VALTOT": self.val_tot, "STATUS": 0, "FLGMOR": 0,
            "NUMDOC": str(self.numtra), "NUMDSP": f"WM{self.cod_ven}",
            "NUMORD": self.numtra, "OBSER1": self.obser1,
            "OBSER2": self.obser2, "VALIMP": 0,
            "NCONSOLIDA": self.numtra, "STATUS2": "",
            "AUTUSR": "", "COMENTARIO": self.comentario,
            "FAUTORIZA": "", "STATENAV": 2,
        }

    def validar(self) -> None:
        if not self.numtra:
            raise ValueError("numtra es requerido")
        if not self.cod_cte:
            raise ValueError("cod_cte es requerido")
        if not self.cod_ven:
            raise ValueError("cod_ven es requerido")


@dataclass
class PedidoDetalle:
    """Order line item — variable fields + context from header."""

    cod_pro: str = ""
    ped_caj: int = 0
    ped_und: int = 0
    fac_emp: int = 0
    val_cto: Decimal = field(default_factory=lambda: Decimal("0"))
    val_vtc: Decimal = field(default_factory=lambda: Decimal("0"))
    val_vts: Decimal = field(default_factory=lambda: Decimal("0"))
    val_esc: Decimal = field(default_factory=lambda: Decimal("0"))
    # Context (filled from header)
    numtra: str = ""
    codlin: int = 0
    num_ped: str = ""
    cod_cte: str = ""
    cod_ven: str = ""
    ano_sis: int = 0
    mes_sis: int = 0
    dia_sis: int = 0
    hor_sis: str = ""

    def to_row(self) -> dict:
        return {
            "NUMTRA": self.numtra, "CODLIN": self.codlin,
            "ANOSIS": self.ano_sis, "CANCAJ": 0, "CANUND": 0,
            "CODBOM": "B", "CODCOR": 0, "CODCTE": self.cod_cte,
            "CODESC": 5, "CODFAC": 1, "CODFAM": 3,
            "CODGFV": 0, "CODGPR": 0, "CODIDE": 0, "CODIMP": 0,
            "CODIVA": 0, "CODPRO": self.cod_pro, "CLACOD": 0,
            "DIASIS": self.dia_sis, "DTOVTC": 0, "DTOVTS": 0,
            "FACEMP": self.fac_emp, "FLGACT": 0, "FLGGPF": 5,
            "HORSIS": self.hor_sis, "MESSIS": self.mes_sis,
            "NOMUSR": self.cod_ven, "NUMARC": 0, "NUMGPO": 0,
            "NUMPED": self.num_ped, "NUMSEC": self.codlin,
            "PEDCAJ": self.ped_caj, "PEDUND": self.ped_und,
            "PESPRO": 0, "PORDTO": 0,
            "VALCTO": self.val_cto, "VALESC": self.val_esc,
            "VALIMP": 0, "VALVTC": self.val_vtc, "VALVTS": self.val_vts,
            "VOLPRO": 0, "STATUS": 0,
            "CAJORI": "", "UNDORI": "", "MARCA": "", "NOHAY": "",
        }

    def validar(self) -> None:
        if not self.cod_pro:
            raise ValueError("cod_pro es requerido")
        if self.ped_caj <= 0 and self.ped_und <= 0:
            raise ValueError("Debe pedir al menos 1 caja o 1 unidad")


# ═══════════════════════════════════════════════════════════════════════════════
# FACTURAS
# ═══════════════════════════════════════════════════════════════════════════════

VIEW_FACTURAS = "dbo.[view_facturas_abiertas]"


@dataclass
class FacturaAbierta:
    """Open invoice — read-only from view."""

    fecha_factura: str = ""
    factura: str = ""
    cod_cte: str = ""
    nombre_cliente: str = ""
    cod_ven: str = ""
    nombre_vendedor: str = ""
    monto_pendiente: Decimal = field(default_factory=lambda: Decimal("0"))

    def to_dict(self) -> dict:
        return {
            "fecha_factura": self.fecha_factura,
            "factura": self.factura,
            "cod_cte": self.cod_cte,
            "nombre_cliente": self.nombre_cliente,
            "cod_ven": self.cod_ven,
            "nombre_vendedor": self.nombre_vendedor,
            "monto_pendiente": str(self.monto_pendiente),
        }

    @classmethod
    def from_row(cls, row: dict) -> FacturaAbierta:
        fecha_raw = row.get("Fecha factura", "")
        if isinstance(fecha_raw, datetime):
            fecha = fecha_raw.strftime("%Y-%m-%d")
        else:
            fecha = str(fecha_raw or "")
        return cls(
            fecha_factura=fecha,
            factura=str(row.get("Factura", "") or ""),
            cod_cte=str(row.get("Código cliente", "") or ""),
            nombre_cliente=str(row.get("Nombre cliente", "") or ""),
            cod_ven=str(row.get("Código vendedor", "") or ""),
            nombre_vendedor=str(row.get("Nombre vendedor", "") or ""),
            monto_pendiente=Decimal(str(row.get("Monto pendiente", 0) or 0)),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SUPPORT (productos, clientes — needed for pedido validations)
# ═══════════════════════════════════════════════════════════════════════════════

VIEW_PRODUCTOS = "dbo.[View_AC_Productos]"
VIEW_EXISTENCIA = "dbo.[View_AC_Existencia]"
VIEW_CLIENTES = "dbo.[View_AC_Clientes]"
