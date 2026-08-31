"""Config — env vars only (no AppConfig, no SSM). This Lambda is in a different VPC."""

import os

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
# SQLSERVER_CONNECTION_STRING is read by shared/db.py (host/user/password/DB).

# ── NAV order tables (company-prefixed in Business Central) ──────────────────
# These MUST be configurable per environment: the NAV company + extension GUID
# differ between the production company ("COMERSAL$T_PEDIDO_ENC") and the test
# company ("PRUEBAS_NAV$T_PEDIDO_ENC$<guid>"). Never hardcode — set the env vars
# per deployment so orders land in the intended company.
#
# You can either provide the full bracketed table names directly:
#     NAV_PEDIDO_ENC_TABLE, NAV_PEDIDO_DET_TABLE
# or build them from parts (company prefix + optional extension GUID):
#     NAV_COMPANY_PREFIX (e.g. "COMERSAL" or "PRUEBAS_NAV")
#     NAV_EXTENSION_GUID (e.g. "326a852b-0bdf-4d79-816d-c14d4187f50c"; empty for
#                         base-app tables like the COMERSAL company)
# Full-name env vars win over the parts. Defaults preserve the historical
# PRUEBAS_NAV (test company) values so behavior is unchanged until configured.

_DEFAULT_COMPANY = "PRUEBAS_NAV"
_DEFAULT_GUID = "326a852b-0bdf-4d79-816d-c14d4187f50c"


def _build_table(base: str) -> str:
    """Build a bracketed NAV table name from the company prefix + optional GUID."""
    company = os.environ.get("NAV_COMPANY_PREFIX", _DEFAULT_COMPANY).strip()
    guid = os.environ.get("NAV_EXTENSION_GUID", _DEFAULT_GUID).strip()
    name = f"{company}${base}" + (f"${guid}" if guid else "")
    return f"[{name}]"


NAV_PEDIDO_ENC_TABLE = os.environ.get("NAV_PEDIDO_ENC_TABLE", "").strip() or _build_table("T_PEDIDO_ENC")
NAV_PEDIDO_DET_TABLE = os.environ.get("NAV_PEDIDO_DET_TABLE", "").strip() or _build_table("T_PEDIDO_DET")

# NUMTRA (order number) series — also company-specific. The PRUEBAS_NAV test
# company uses "PIA-" + 10 digits; the COMERSAL production company uses a
# different series (e.g. "APP*"). Configurable so switching companies is a
# deploy-time env change, not a code edit.
NAV_NUMTRA_PREFIX = os.environ.get("NAV_NUMTRA_PREFIX", "PIA-")
NAV_NUMTRA_PAD_LENGTH = int(os.environ.get("NAV_NUMTRA_PAD_LENGTH", "10"))
