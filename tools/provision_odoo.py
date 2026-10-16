#!/usr/bin/env python3
"""Configura una base de Odoo 19 para usar el simulador de la DIAN en un solo paso.

Qué hace (todo contra una base de PRUEBAS; no la ejecutes en producción):
  1. Lee las credenciales ficticias que genera el simulador (/api/credentials).
  2. Ajusta la compañía: país Colombia, NIT del emisor, régimen y responsabilidad fiscal, CIIU.
  3. Configura el diario de ventas en modo "Habilitación" con Software ID, PIN, TestSetId, resolución y clave técnica.
  4. Sube el certificado .p12 de prueba que entrega el simulador.
  5. Asigna el tipo de impuesto DIAN a los impuestos y crea un cliente y un producto de prueba.

Requiere los módulos OCA l10n_co_electronic_invoice y l10n_co_electronic_invoice_self (Odoo 19) instalados.
Solo usa la biblioteca estándar de Python.

Uso:
  python tools/provision_odoo.py --sandbox http://localhost:8099 --odoo http://localhost:8069 \
      --db mi_base --user admin --password admin
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.request
import xmlrpc.client

WEIGHTS = [3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71]


def check_digit(nit: str) -> str:
    total = sum(int(d) * WEIGHTS[i] for i, d in enumerate(reversed(nit)))
    rest = total % 11
    return str(rest if rest < 2 else 11 - rest)


class Odoo:
    def __init__(self, url, db, user, password, dry_run=False):
        self.db, self.password, self.dry = db, password, dry_run
        common = xmlrpc.client.ServerProxy(url.rstrip("/") + "/xmlrpc/2/common", allow_none=True)
        self.uid = common.authenticate(db, user, password, {})
        if not self.uid:
            sys.exit("No se pudo iniciar sesión en Odoo: revisa base, usuario y contraseña.")
        self.models = xmlrpc.client.ServerProxy(url.rstrip("/") + "/xmlrpc/2/object", allow_none=True)

    def call(self, model, method, *args, **kwargs):
        return self.models.execute_kw(self.db, self.uid, self.password, model, method, list(args), kwargs)

    def search(self, model, domain, **kw):
        return self.call(model, "search", domain, **kw)

    def write(self, model, ids, vals):
        if self.dry:
            print(f"   [simulación] write {model} {ids}: {sorted(vals)}")
            return True
        return self.call(model, "write", ids, vals)

    def create(self, model, vals):
        if self.dry:
            print(f"   [simulación] create {model}: {vals.get('name')}")
            return 0
        return self.call(model, "create", vals)


def fetch(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sandbox", default="http://localhost:8099", help="URL base del simulador")
    ap.add_argument("--odoo", default="http://localhost:8069")
    ap.add_argument("--db", required=True)
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="admin")
    ap.add_argument("--journal", default="", help="Código del diario de ventas (por defecto el primero de ventas)")
    ap.add_argument("--dry-run", action="store_true", help="Muestra qué haría sin escribir nada")
    a = ap.parse_args()

    print(f"Simulador: {a.sandbox}")
    creds = json.loads(fetch(a.sandbox.rstrip("/") + "/api/credentials"))
    nit = creds["issuer_nit"]
    vat = f"{nit}-{check_digit(nit)}"
    o = Odoo(a.odoo, a.db, a.user, a.password, a.dry_run)
    print(f"Odoo: {a.odoo} base '{a.db}' (uid {o.uid})")

    def one(model, domain, fields=("id",)):
        r = o.call(model, "search_read", domain, fields=list(fields), limit=1)
        return r[0] if r else None

    co = one("res.country", [("code", "=", "CO")])["id"]
    state = one("res.country.state", [("country_id", "=", co), ("code", "=", "11")])
    city = one("res.city", [("state_id", "=", state["id"])]) if state else None
    nit_type = one("l10n_latam.identification.type", [("name", "=", "NIT")])
    resp = one("l10n_co.responsibility.type", [("code", "=", "R-99-PN")])
    ciiu = one("l10n_co.ciiu", [("code", "=", "6201")]) or one("l10n_co.ciiu", [])
    if not (nit_type and resp):
        sys.exit("Faltan datos de la localización: instala l10n_co_electronic_invoice y l10n_co_electronic_invoice_self.")

    # 1. Compañía
    company = one("res.company", [], ["partner_id", "name"])
    print(f"1. Compañía '{company['name']}' -> {creds['issuer_name']} ({vat})")
    o.write("res.partner", [company["partner_id"][0]], {
        "name": creds["issuer_name"], "country_id": co, "state_id": state and state["id"], "city_id": city and city["id"],
        "city": "BOGOTA", "zip": "110111", "street": "CALLE FICTICIA 1 # 2-3", "email": "emisor@example.com",
        "phone": "6010000000", "l10n_latam_identification_type_id": nit_type["id"], "vat": vat})
    o.write("res.company", [company["id"]], {
        "country_id": co, "name": creds["issuer_name"], "l10n_co_regimen_fiscal": "48",
        "l10n_co_responsibility_ids": [(6, 0, [resp["id"]])], "l10n_co_ciiu_id": ciiu and ciiu["id"]})

    # 2. Diario
    domain = [("type", "=", "sale")] + ([("code", "=", a.journal)] if a.journal else [])
    journal = one("account.journal", domain, ["name"])
    rng = (creds.get("numbering_ranges") or [{}])[0]
    fmt = one("account.edi.format", [("code", "=", "l10n_co_dian_self")])
    print(f"2. Diario '{journal['name']}' en modo Habilitación (prefijo {rng.get('prefix')}, rango "
          f"{rng.get('from_number')}-{rng.get('to_number')})")
    o.write("account.journal", [journal["id"]], {
        "l10n_co_dian_operation_mode": "test", "l10n_latam_use_documents": True,
        "l10n_co_dian_software_identification": creds["software_id"], "l10n_co_dian_software_pin": creds["software_pin"],
        "l10n_co_dian_test_set_id": creds["test_set_id"], "l10n_co_dian_software_technical_key_test": creds["technical_key"],
        "l10n_co_electronic_document_prefix_test": rng.get("prefix", "SETP"),
        "l10n_co_electronic_document_start_number_test": int(rng.get("from_number", 990000000)),
        "l10n_co_electronic_document_end_number_test": int(rng.get("to_number", 995000000)),
        "l10n_co_electronic_document_resolution_test": rng.get("resolution", "000000000"),
        "l10n_co_electronic_document_start_resolution_date_test": rng.get("valid_from") or "2019-01-19",
        "l10n_co_electronic_document_end_resolution_date_test": rng.get("valid_to") or "2030-01-19",
        **({"edi_format_ids": [(4, fmt["id"])]} if fmt else {}),
    })

    # 3. Certificado de prueba
    print("3. Certificado de prueba (.p12) del simulador")
    p12 = fetch(creds["certificate_url"])
    name = "SANDBOX DIAN (certificado de PRUEBA)"
    if one("certificate.certificate", [("name", "=", name)]):
        print("   ya existía; no se vuelve a subir")
    else:
        o.create("certificate.certificate", {
            "name": name, "content": base64.b64encode(p12).decode(), "pkcs12_password": creds["certificate_password"],
            "company_id": company["id"]})

    # 4. Impuestos
    types = {t["code"]: t["id"] for t in o.call("l10n_co.tax.type", "search_read", [], fields=["code"])}
    changed = 0
    for tax in o.call("account.tax", "search_read", [], fields=["name", "l10n_co_tax_type_id"]):
        if tax["l10n_co_tax_type_id"]:
            continue
        n = tax["name"]
        code = ("06" if "RteFte" in n else "05" if "RteVAT" in n else "07" if "RteICA" in n
                else "04" if "INC" in n else "ZA" if "EXC" in n else "01")
        if code in types:
            o.write("account.tax", [tax["id"]], {"l10n_co_tax_type_id": types[code]})
            changed += 1
    print(f"4. Tipo de impuesto DIAN asignado a {changed} impuestos")

    # 5. Cliente y producto de prueba
    cust_nit = "900000002"
    if not one("res.partner", [("vat", "=", f"{cust_nit}-{check_digit(cust_nit)}")]):
        o.create("res.partner", {
            "name": "CLIENTE DE PRUEBAS SANDBOX SAS", "is_company": True, "country_id": co,
            "state_id": state and state["id"], "city_id": city and city["id"], "city": "BOGOTA",
            "street": "CARRERA FICTICIA 4 # 5-6", "email": "cliente@example.com",
            "l10n_latam_identification_type_id": nit_type["id"], "vat": f"{cust_nit}-{check_digit(cust_nit)}",
            "l10n_co_regimen_fiscal": "48", "l10n_co_responsibility_ids": [(6, 0, [resp["id"]])]})
    if not one("product.template", [("name", "=", "Servicio de pruebas sandbox")]):
        unspsc = one("product.unspsc", [])
        o.create("product.template", {"name": "Servicio de pruebas sandbox", "type": "service", "list_price": 100000,
                                      "product_unspsc_id": unspsc and unspsc["id"]})
    print("5. Cliente y producto de prueba listos")

    print("\nListo. Falta solo una cosa en el servidor de Odoo: apuntar el módulo al simulador.")
    print(f"   Instala el addon l10n_co_dian_sandbox_connector y arranca Odoo con  DIAN_SANDBOX_URL={creds['soap_url']}")
    print("   (o agrega  dian_sandbox_url = ...  en la sección [options] de odoo.conf). Después crea una factura y confírmala.")


if __name__ == "__main__":
    main()
