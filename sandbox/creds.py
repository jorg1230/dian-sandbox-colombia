"""Generación de las credenciales de pruebas: lo mismo que la DIAN entrega al registrar un software."""
from __future__ import annotations

import secrets
import uuid

from .ubl import nit_check_digit


def new_credentials() -> dict:
    """Credenciales ficticias y aleatorias para conectar un cliente (por ejemplo Odoo) al simulador."""
    nit = "9" + "".join(secrets.choice("0123456789") for _ in range(8))
    return {
        "software_id": str(uuid.uuid4()),
        "software_pin": "".join(secrets.choice("0123456789") for _ in range(5)),
        "test_set_id": str(uuid.uuid4()),
        "technical_key": secrets.token_hex(20),
        "issuer_nit": nit,
        "issuer_name": "EMPRESA DE PRUEBAS SANDBOX SAS",
        "cert_password": "sandbox",
    }


def issuer_vat(settings: dict) -> str:
    nit = settings.get("issuer_nit", "")
    return f"{nit}-{nit_check_digit(nit)}" if nit else ""
