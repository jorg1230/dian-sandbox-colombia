"""Certificado de PRUEBA para firmar documentos contra el simulador.

Genera una CA y un certificado hoja autofirmados, claramente marcados como de prueba, y los empaqueta como
PKCS#12 (.p12) para cargarlos en el software que firma (por ejemplo el módulo de Odoo). Estos certificados
NO sirven ante la DIAN real ni ante ninguna entidad certificadora.
"""
from __future__ import annotations

import datetime as dt

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

DEV_ORG = "SANDBOX NO OFICIAL - SOLO DESARROLLO"


def _name(common_name: str, nit: str | None = None) -> x509.Name:
    attrs = [
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CO"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, DEV_ORG),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ]
    if nit:
        attrs.append(x509.NameAttribute(NameOID.SERIAL_NUMBER, nit))
    return x509.Name(attrs)


def generate_p12(nit: str, subject_cn: str, password: str, days: int = 3650) -> tuple[bytes, dict]:
    """Devuelve (bytes del .p12, información del certificado)."""
    now = dt.datetime.now(dt.timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = _name("CA de pruebas SANDBOX (no es una entidad certificadora)")
    ca_cert = (
        x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (
        x509.CertificateBuilder().subject_name(_name(subject_cn, nit)).issuer_name(ca_name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=True, key_encipherment=False,
                                     data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                     crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    p12 = pkcs12.serialize_key_and_certificates(
        name=b"sandbox-dian", key=key, cert=cert, cas=[ca_cert],
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode("utf-8")))
    info = {
        "subject": cert.subject.rfc4514_string(),
        "serial": str(cert.serial_number),
        "not_before": cert.not_valid_before_utc.isoformat(),
        "not_after": cert.not_valid_after_utc.isoformat(),
        "ca_subject": ca_cert.subject.rfc4514_string(),
    }
    return p12, info
