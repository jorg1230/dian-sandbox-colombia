#!/usr/bin/env python3
"""Envía los documentos de samples/ al simulador por SOAP (SendTestSetAsync + GetStatusZip), sin necesitar Odoo.

Sirve para ver el simulador funcionando y como ejemplo mínimo de cliente. Uso:
    python tools/send_samples.py --sandbox http://127.0.0.1:8099
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import urllib.request
import zipfile

SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "samples")
ORDER = ["invoice__fv", "credit_note__nc", "debit_note__nd", "payroll__nomina"]


def soap(url: str, op: str, **fields) -> str:
    inner = "".join(f"<wcf:{k}>{v}</wcf:{k}>" for k, v in fields.items())
    body = (
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:wcf="http://wcf.dian.colombia">'
        f"<soap:Header/><soap:Body><wcf:{op}>{inner}</wcf:{op}></soap:Body></soap:Envelope>").encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/soap+xml; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def tag(xml: str, name: str) -> str:
    m = re.search(rf"<(?:\w+:)?{name}>(.*?)</(?:\w+:)?{name}>", xml, re.S)
    return m.group(1) if m else ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sandbox", default="http://127.0.0.1:8099")
    ap.add_argument("--align", action="store_true",
                    help="antes de enviar, ajusta el simulador a los datos de samples/ (Software ID, PIN, clave técnica, NIT)")
    a = ap.parse_args()
    base = a.sandbox.rstrip("/")
    if a.align:
        urllib.request.urlopen(urllib.request.Request(base + "/settings/align-samples", data=b"", method="POST"), timeout=30)
        print("Simulador ajustado a los datos de las muestras.")
    creds = json.loads(urllib.request.urlopen(base + "/api/credentials").read())
    url = creds["soap_url"]
    print(f"Simulador {base} — TestSetId {creds['test_set_id']}\n")
    print("Nota: los documentos de samples/ están firmados con los datos fijos de las muestras; el simulador los acepta "
          "si su configuración coincide (Software ID, PIN, clave técnica y NIT de samples/meta.json).")
    meta = json.load(open(os.path.join(SAMPLES, "meta.json"), encoding="utf8"))
    print(f"  Configura en el simulador: NIT {meta['issuer_nit']}, Software ID {meta['software_id']}, PIN {meta['pin']}, "
          f"clave técnica {meta['technical_key']}.\n")
    for prefix in ORDER:
        for fname in sorted(os.listdir(SAMPLES)):
            if fname.startswith(prefix) and fname.endswith(".xml"):
                xml = open(os.path.join(SAMPLES, fname), "rb").read()
                buf = io.BytesIO()
                name = fname.split("__", 1)[1]
                with zipfile.ZipFile(buf, "w") as zf:
                    zf.writestr(name, xml)
                resp = soap(url, "SendTestSetAsync", fileName=name.replace(".xml", ".zip"),
                            contentFile=base64.b64encode(buf.getvalue()).decode(), testSetId=creds["test_set_id"])
                zip_key = tag(resp, "ZipKey")
                if not zip_key:
                    print(f"  {fname}: el simulador no aceptó el envío: {tag(resp, 'string')}")
                    continue
                st = soap(url, "GetStatusZip", trackId=zip_key)
                print(f"  {fname:<55} StatusCode {tag(st, 'StatusCode')}  {tag(st, 'StatusDescription')}")
                errors = re.findall(r"<(?:\w+:)?string>(.*?)</(?:\w+:)?string>", st)
                for e in errors:
                    print(f"      - {e}")
    print("\nMira el resultado en", base + "/")


if __name__ == "__main__":
    main()
