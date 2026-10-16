"""Aplicación Flask: servicio SOAP simulado + interfaz gráfica.  SOLO PARA DESARROLLO."""
from __future__ import annotations

import io
import json
import os
import zipfile

from flask import (Flask, Response, abort, flash, jsonify, redirect, render_template, request, send_file,
                   url_for)
from lxml import etree

from . import BANNER, TAG, __version__
from .creds import issuer_vat
from .pki import generate_p12
from .processor import Processor
from .soap import DianService, build_wsdl
from .store import Store
from .ubl import EVENT_CODES, KIND_LABELS

SOAP_PATH = "/WcfDianCustomerServices.svc"


def create_app(data_dir: str | None = None) -> Flask:
    data_dir = data_dir or os.environ.get("SANDBOX_DATA_DIR", os.path.join(os.getcwd(), "data"))
    if data_dir != ":memory:":
        os.makedirs(data_dir, exist_ok=True)
    app = Flask(__name__)
    app.secret_key = os.environ.get("SANDBOX_SECRET", "sandbox-solo-desarrollo")
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
    store = Store(os.path.join(data_dir, "sandbox.db") if data_dir != ":memory:" else ":memory:")
    processor = Processor(store)
    service = DianService(processor)
    app.extensions["sandbox"] = {"store": store, "processor": processor, "service": service, "data_dir": data_dir}

    @app.context_processor
    def inject():
        return {"BANNER": BANNER, "TAG": TAG, "VERSION": __version__, "KIND_LABELS": KIND_LABELS,
                "soap_url": request.host_url.rstrip("/") + SOAP_PATH}

    @app.after_request
    def mark(resp):
        resp.headers["X-Sandbox"] = "dian-sandbox-colombia; solo desarrollo; no oficial"
        return resp

    # -------------------------------------------------------------------- SOAP
    @app.route(SOAP_PATH, methods=["GET", "POST"])
    def soap():
        if request.method == "GET":
            if "wsdl" in request.args:
                store.log_op("WSDL")
                return Response(build_wsdl(request.host_url.rstrip("/") + SOAP_PATH),
                                mimetype="text/xml; charset=utf-8")
            return Response(f"{TAG} Servicio SOAP simulado de la DIAN. Agrega ?wsdl para ver el contrato.\n",
                            mimetype="text/plain; charset=utf-8")
        body, status = service.handle(request.get_data(), request.headers.get("SOAPAction", ""))
        return Response(body, status=status, mimetype="application/soap+xml; charset=utf-8")

    # ---------------------------------------------------------------------- UI
    @app.route("/")
    def dashboard():
        return render_template("dashboard.html", progress=processor.set_progress(), totals=store.totals(),
                               docs=store.documents(limit=10), settings=store.settings())

    @app.route("/readiness")
    def readiness():
        return render_template("readiness.html", checks=processor.readiness(), progress=processor.set_progress())

    @app.route("/rules")
    def rules():
        from . import dian_rules
        grouped: dict = {}
        for code, (family, severity, desc, ref) in sorted(dian_rules.RULES.items()):
            grouped.setdefault(family, []).append((code, severity, desc, ref))
        return render_template("rules.html", grouped=grouped)

    @app.route("/api/readiness")
    def api_readiness():
        return jsonify({"checks": processor.readiness(), "progress": processor.set_progress()})

    @app.route("/documents")
    def documents():
        kind, status = request.args.get("kind", ""), request.args.get("status", "")
        return render_template("documents.html", docs=store.documents(limit=2000, kind=kind, status=status),
                               kind=kind, status=status)

    @app.route("/documents/<int:doc_id>")
    def document(doc_id):
        doc = store.document(doc_id)
        if not doc:
            abort(404)
        try:
            pretty = etree.tostring(etree.fromstring(doc["xml"]), pretty_print=True).decode("utf-8")
        except Exception:
            pretty = (doc["xml"] or b"").decode("utf-8", "replace")
        return render_template("document.html", doc=doc, pretty=pretty, event_codes=EVENT_CODES)

    @app.route("/documents/<int:doc_id>/xml")
    def document_xml(doc_id):
        doc = store.document(doc_id)
        if not doc:
            abort(404)
        return Response(doc["xml"], mimetype="application/xml",
                        headers={"Content-Disposition": f"attachment; filename={doc['file_name'] or doc_id}.xml"})

    @app.route("/upload", methods=["GET", "POST"])
    def upload():
        if request.method == "POST":
            files = request.files.getlist("files")
            last = None
            for f in files:
                raw = f.read()
                if not raw:
                    continue
                if f.filename.lower().endswith(".zip"):
                    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                        for info in zf.infolist():
                            if info.filename.lower().endswith(".xml"):
                                last = processor.process(zf.read(info), info.filename, "", "", "upload")
                else:
                    last = processor.process(raw, f.filename, "", "", "upload")
            if last:
                return redirect(url_for("document", doc_id=last["id"]))
            flash("No se recibió ningún archivo.")
        return render_template("upload.html")

    @app.route("/connect")
    def connect():
        s = store.settings()
        return render_template("connect.html", s=s, vat=issuer_vat(s), ranges=store.ranges())

    @app.route("/connect/certificate.p12")
    def certificate():
        s = store.settings()
        path = os.path.join(data_dir, "sandbox_cert.p12") if data_dir != ":memory:" else None
        if path and os.path.exists(path):
            raw = open(path, "rb").read()
        else:
            raw, info = generate_p12(s["issuer_nit"], s.get("issuer_name", "SANDBOX"), s["cert_password"])
            if path:
                open(path, "wb").write(raw)
                open(path + ".json", "w").write(json.dumps(info))
        return send_file(io.BytesIO(raw), mimetype="application/x-pkcs12", as_attachment=True,
                         download_name="certificado_PRUEBA_sandbox.p12")

    @app.route("/settings", methods=["GET", "POST"])
    def settings():
        if request.method == "POST":
            f = request.form
            values = {k: f[k].strip() for k in (
                "software_id", "software_pin", "test_set_id", "technical_key", "issuer_nit", "issuer_name",
                "cert_password", "need_invoices", "need_credit_notes", "need_debit_notes", "need_payrolls", "uvt_value",
                "max_age_days") if k in f}
            for flag in ("verify_signature", "verify_cufe", "verify_totals", "allow_external_references",
                         "require_environment_2", "dian_filter"):
                values[flag] = "1" if f.get(flag) else "0"
            store.set_settings(values)
            ranges = []
            for i in range(0, 20):
                if f.get(f"r_prefix_{i}") is None:
                    break
                if f.get(f"r_prefix_{i}", "").strip() or f.get(f"r_from_{i}", "").strip():
                    ranges.append({"resolution": f.get(f"r_resolution_{i}", ""), "prefix": f.get(f"r_prefix_{i}", ""),
                                   "from_number": f.get(f"r_from_{i}") or 0, "to_number": f.get(f"r_to_{i}") or 0,
                                   "valid_from": f.get(f"r_vfrom_{i}", ""), "valid_to": f.get(f"r_vto_{i}", ""),
                                   "technical_key": f.get(f"r_key_{i}", "")})
            store.replace_ranges(ranges)
            cert = os.path.join(data_dir, "sandbox_cert.p12")
            if data_dir != ":memory:" and os.path.exists(cert):
                os.remove(cert)  # se regenera con el nuevo NIT/contraseña
            flash("Configuración guardada.")
            return redirect(url_for("settings"))
        rngs = store.ranges() + [{"resolution": "", "prefix": "", "from_number": "", "to_number": "",
                                  "valid_from": "", "valid_to": "", "technical_key": ""}]
        return render_template("settings.html", s=store.settings(), ranges=rngs)

    @app.route("/settings/align-samples", methods=["POST"])
    def align_samples():
        """Ajusta credenciales y rango a los de los documentos de samples/ (firmados con datos fijos)."""
        meta_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples", "meta.json")
        if not os.path.exists(meta_path):
            flash("No se encontró samples/meta.json.")
            return redirect(url_for("settings"))
        meta = json.load(open(meta_path, encoding="utf8"))
        store.set_settings({"software_id": meta["software_id"], "software_pin": meta["pin"],
                            "technical_key": meta["technical_key"], "issuer_nit": meta["issuer_nit"]})
        flash("Configuración ajustada a los documentos de muestra (samples/).")
        return redirect(url_for("settings"))

    @app.route("/reset", methods=["POST"])
    def reset():
        store.reset_documents()
        flash("Documentos borrados. Las credenciales y rangos se conservan.")
        return redirect(url_for("dashboard"))

    # --------------------------------------------------------------------- API
    @app.route("/api/credentials")
    def api_credentials():
        s = store.settings()
        return jsonify({
            "aviso": TAG + " credenciales ficticias generadas por el simulador",
            "soap_url": request.host_url.rstrip("/") + SOAP_PATH,
            "wsdl_url": request.host_url.rstrip("/") + SOAP_PATH + "?wsdl",
            "issuer_nit": s["issuer_nit"], "issuer_dv": issuer_vat(s).split("-")[-1],
            "issuer_name": s["issuer_name"], "software_id": s["software_id"], "software_pin": s["software_pin"],
            "test_set_id": s["test_set_id"], "technical_key": s["technical_key"],
            "numbering_ranges": store.ranges(),
            "certificate_url": request.host_url.rstrip("/") + "/connect/certificate.p12",
            "certificate_password": s["cert_password"],
            "test_set_requirements": {"invoices": s["need_invoices"], "credit_notes": s["need_credit_notes"],
                                      "debit_notes": s["need_debit_notes"]},
        })

    @app.route("/api/documents")
    def api_documents():
        docs = store.documents(limit=int(request.args.get("limit", 100)), kind=request.args.get("kind", ""),
                               status=request.args.get("status", ""))
        for d in docs:
            d.pop("xml", None)
        return jsonify(docs)

    @app.route("/api/progress")
    def api_progress():
        return jsonify(processor.set_progress())

    @app.route("/health")
    def health():
        return jsonify({"ok": True, "version": __version__, "aviso": TAG})

    return app


def main():
    host = os.environ.get("SANDBOX_HOST", "127.0.0.1")
    port = int(os.environ.get("SANDBOX_PORT", "8099"))
    app = create_app()
    print(f"\n  {BANNER}\n  Servicio SOAP: http://{host}:{port}{SOAP_PATH}\n  Interfaz:      http://{host}:{port}/\n")
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
