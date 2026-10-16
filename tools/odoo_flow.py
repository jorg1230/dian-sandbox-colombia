#!/usr/bin/env python3
"""Genera en Odoo (por XML-RPC) una factura, notas crédito y notas débito, las envía al simulador y muestra el resultado.

Sirve para ejercitar el flujo completo de habilitación con un software contable real. Solo para bases de PRUEBAS.
Requiere haber ejecutado antes tools/provision_odoo.py y tener el conector instalado.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import xmlrpc.client


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sandbox", default="http://localhost:8099")
    ap.add_argument("--odoo", default="http://localhost:8069")
    ap.add_argument("--db", required=True)
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="admin")
    ap.add_argument("--credit-notes", type=int, default=2)
    ap.add_argument("--debit-notes", type=int, default=2)
    a = ap.parse_args()

    uid = xmlrpc.client.ServerProxy(a.odoo + "/xmlrpc/2/common").authenticate(a.db, a.user, a.password, {})
    if not uid:
        sys.exit("No se pudo iniciar sesión en Odoo.")
    models = xmlrpc.client.ServerProxy(a.odoo + "/xmlrpc/2/object", allow_none=True)

    def call(model, method, *args, **kw):
        try:
            return models.execute_kw(a.db, uid, a.password, model, method, list(args), kw)
        except xmlrpc.client.Fault as exc:
            lines = [l for l in str(exc.faultString).splitlines() if l.strip()]
            if "cannot marshal None" in str(exc.faultString):
                return None  # la acción se ejecutó; el XML-RPC de Odoo no puede devolver None
            sys.exit(f"Error de Odoo en {model}.{method}: {lines[-1] if lines else exc.faultString}")

    def one(model, domain):
        r = call(model, "search", domain, limit=1)
        return r[0] if r else None

    def doc_type(code):
        return one("l10n_latam.document.type", [("country_id.code", "=", "CO"), ("code", "=", code)])

    journal = one("account.journal", [("type", "=", "sale")])
    customer = one("res.partner", [("name", "=", "CLIENTE DE PRUEBAS SANDBOX SAS")])
    product = call("product.product", "search", [("name", "=", "Servicio de pruebas sandbox")], limit=1)[0]
    tax = one("account.tax", [("type_tax_use", "=", "sale"), ("amount", "=", 19)])
    if not (journal and customer and product and tax):
        sys.exit("Faltan datos de prueba: ejecuta primero tools/provision_odoo.py.")

    def send(move_id, label):
        call("account.move", "action_process_edi_web_services", [move_id])  # envía (SendTestSetAsync)
        call("account.move", "action_query_dian_status", [move_id])  # consulta el resultado (GetStatusZip)
        m = call("account.move", "read", [move_id], fields=["name", "l10n_co_dian_status", "edi_error_message"])[0]
        print(f"  {label:<14} {m['name']:<16} estado DIAN: {m['l10n_co_dian_status']} {m['edi_error_message'] or ''}")
        return m

    print("Factura")
    inv = call("account.move", "create", {
        "move_type": "out_invoice", "partner_id": customer, "journal_id": journal,
        "l10n_latam_document_type_id": doc_type("01"),
        "invoice_line_ids": [(0, 0, {"product_id": product, "quantity": 2, "price_unit": 100000, "tax_ids": [(6, 0, [tax])]})]})
    call("account.move", "action_post", [inv])
    send(inv, "Factura")

    print("Notas crédito")
    for i in range(a.credit_notes):
        wiz = call("account.move.reversal", "create", {"reason": f"Devolución {i + 1}", "journal_id": journal},
                   context={"active_model": "account.move", "active_ids": [inv]})
        nc = call("account.move.reversal", "refund_moves", [wiz], context={"active_model": "account.move", "active_ids": [inv]})["res_id"]
        call("account.move", "write", [nc], {"l10n_latam_document_type_id": doc_type("91"), "l10n_co_discrepancy_response_code": "nc_2"})
        call("account.move", "action_post", [nc])
        send(nc, f"Nota crédito {i + 1}")

    print("Notas débito")
    for i in range(a.debit_notes):
        wiz = call("account.debit.note", "create", {"reason": f"Ajuste {i + 1}", "copy_lines": True},
                   context={"active_model": "account.move", "active_ids": [inv]})
        nd = call("account.debit.note", "create_debit", [wiz], context={"active_model": "account.move", "active_ids": [inv]})["res_id"]
        call("account.move", "write", [nd], {"l10n_latam_document_type_id": doc_type("92"), "l10n_co_discrepancy_response_code": "nd_3"})
        call("account.move", "action_post", [nd])
        send(nd, f"Nota débito {i + 1}")

    progress = json.loads(urllib.request.urlopen(a.sandbox + "/api/progress").read())
    print("\nSet de pruebas en el simulador:", "COMPLETO" if progress["complete"] else "incompleto")
    for r in progress["rows"]:
        print(f"  {r['label']}: {r['have']}/{r['need']}")


if __name__ == "__main__":
    main()
