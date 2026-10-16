"""Procesa un XML recibido: lo lee, aplica las reglas y lo guarda con su resultado."""
from __future__ import annotations

from . import ubl
from .store import Store


class Processor:
    def __init__(self, store: Store):
        self.store = store

    def _ctx(self) -> dict:
        return {
            "settings": self.store.settings(),
            "ranges": self.store.ranges(),
            "accepted_by_number": self.store.accepted_by_number,
            "accepted_by_uuid": self.store.accepted_by_uuid,
        }

    def process(self, xml: bytes, file_name: str = "", zip_key: str = "", test_set_id: str = "",
                via: str = "upload") -> dict:
        parsed, root, findings = ubl.parse(xml)
        extra: dict = {}
        if parsed is not None:
            more, extra = ubl.validate(parsed, root, self._ctx())
            findings += more
        accepted = ubl.is_accepted(findings)
        pdict = parsed.as_dict() if parsed else {}
        pdict["extra"] = {**pdict.get("extra", {}), **extra}
        doc = {
            "track_id": zip_key or (parsed.uuid if parsed else ""),
            "zip_key": zip_key,
            "file_name": file_name,
            "test_set_id": test_set_id,
            "via": via,
            "kind": parsed.kind if parsed else "unknown",
            "number": parsed.number if parsed else "",
            "uuid": parsed.uuid if parsed else "",
            "issuer_nit": parsed.issuer_nit if parsed else "",
            "customer_id": parsed.customer_id if parsed else "",
            "payable": parsed.payable if parsed else "",
            "issue_date": parsed.issue_date if parsed else "",
            "status_code": "00" if accepted else "99",
            "is_valid": 1 if accepted else 0,
            "findings": [f.as_dict() for f in findings],
            "parsed": pdict,
            "xml": xml,
        }
        doc_id = self.store.add_document(doc)
        return self.store.document(doc_id)

    # --------------------------------------------------------- set de pruebas
    def set_progress(self) -> dict:
        s = self.store.settings()
        counts = self.store.counts(s.get("test_set_id") or None)
        need = {
            "invoice": int(s.get("need_invoices", 1)),
            "credit_note": int(s.get("need_credit_notes", 2)),
            "debit_note": int(s.get("need_debit_notes", 2)),
        }
        if int(s.get("need_payrolls", 0)):
            need["payroll"] = int(s["need_payrolls"])
        rows = [{"kind": k, "label": ubl.KIND_LABELS[k], "have": counts.get(k, 0), "need": n,
                 "done": counts.get(k, 0) >= n} for k, n in need.items()]
        return {"rows": rows, "complete": all(r["done"] for r in rows)}

    # --------------------------------------------------------- lista de preparación
    def readiness(self) -> list[dict]:
        """Lista de verificación de lo que el simulador ya vio de tu software. 'required' = pide el set de pruebas."""
        progress = self.set_progress()
        ops = self.store.ops_seen()
        docs = self.store.documents(limit=500)
        accepted = [d for d in docs if d["is_valid"]]
        checks: list[dict] = []

        def add(key, title, ok, required, detail=""):
            checks.append({"key": key, "title": title, "ok": bool(ok), "required": required, "detail": detail})

        for r in progress["rows"]:
            add(f"set_{r['kind']}", f"{r['label']}: {r['need']} aceptada(s) en el set de pruebas", r["done"], True,
                f"{r['have']} de {r['need']}")
        add("send_test_set", "El software envía con SendTestSetAsync y el TestSetId", ops.get("SendTestSetAsync", 0) > 0,
            True)
        add("status", "El software consulta el resultado (GetStatusZip o GetStatus)",
            ops.get("GetStatusZip", 0) + ops.get("GetStatus", 0) > 0, True,
            "La DIAN responde de forma asíncrona: hay que consultar el estado antes de generar notas.")
        certs = [d["parsed"].get("extra", {}).get("certificate") for d in accepted]
        add("signed", "Los documentos aceptados vienen firmados con un certificado vigente",
            any(c for c in certs), True)
        # reenvío corregido: un número rechazado que luego se aceptó
        rejected_numbers = {d["number"] for d in docs if not d["is_valid"] and d["number"]}
        resent = [n for n in rejected_numbers if any(d["number"] == n and d["is_valid"] for d in docs)]
        add("resend", "Manejo de rechazos: un documento rechazado se corrigió y se reenvió con el mismo número",
            bool(resent), False, ", ".join(sorted(resent)[:5]))
        recent = docs[:10]
        rate = (sum(1 for d in recent if d["is_valid"]) / len(recent)) if recent else 0
        add("rate", "Tasa de aceptación de los últimos envíos ≥ 80 %", bool(recent) and rate >= 0.8, False,
            f"{round(rate * 100)} % de {len(recent)}")
        add("numbering", "El software consulta los rangos de numeración (GetNumberingRange)",
            ops.get("GetNumberingRange", 0) > 0, False)
        add("wsdl", "El software descarga el WSDL", ops.get("WSDL", 0) > 0, False)
        kinds = {d["kind"] for d in accepted}
        add("support", "Documento soporte aceptado", "support_document" in kinds, False)
        add("payroll", "Nómina electrónica aceptada", "payroll" in kinds, False)
        add("event", "Evento RADIAN aceptado (acuse, recibo, aceptación)", "event" in kinds, False)
        return checks
