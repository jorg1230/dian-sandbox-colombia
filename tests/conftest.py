import base64
import io
import json
import os
import zipfile

import pytest

os.environ["SANDBOX_FIXED_CREDENTIALS"] = "1"

from sandbox.app import create_app  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "samples")
META = json.load(open(os.path.join(SAMPLES, "meta.json"), encoding="utf8"))
TEST_SET = "00000000-0000-4000-8000-0000000000aa"


def sample(kind: str) -> tuple[str, bytes]:
    """Devuelve (nombre, xml) del documento de muestra (sin el AttachedDocument)."""
    if kind == "payroll":
        return "nomina_individual.xml", open(os.path.join(SAMPLES, "payroll__nomina_individual.xml"), "rb").read()
    name = [f for f in META[kind]["files"] if not f.startswith("ad")][0]
    return name, open(os.path.join(SAMPLES, f"{kind}__{name}"), "rb").read()


def zip_b64(name: str, xml: bytes) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, xml)
    return base64.b64encode(buf.getvalue()).decode()


def soap(op: str, **fields) -> bytes:
    inner = "".join(f"<wcf:{k}>{v}</wcf:{k}>" for k, v in fields.items())
    return (
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:wcf="http://wcf.dian.colombia">'
        f"<soap:Header/><soap:Body><wcf:{op}>{inner}</wcf:{op}></soap:Body></soap:Envelope>"
    ).encode()


@pytest.fixture()
def app():
    app = create_app(":memory:")
    store = app.extensions["sandbox"]["store"]
    store.set_settings({
        "software_id": META["software_id"], "software_pin": META["pin"], "technical_key": META["technical_key"],
        "issuer_nit": META["issuer_nit"], "test_set_id": TEST_SET,
    })
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def store(app):
    return app.extensions["sandbox"]["store"]


@pytest.fixture()
def processor(app):
    return app.extensions["sandbox"]["processor"]
