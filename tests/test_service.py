import io
import re

from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree

from sandbox import ubl
from tests.conftest import META, TEST_SET, sample, soap, zip_b64


def uuid_of(kind):
    return ubl.parse(sample(kind)[1])[0].uuid


def post(client, op, **fields):
    r = client.post("/WcfDianCustomerServices.svc", data=soap(op, **fields),
                    headers={"Content-Type": "application/soap+xml"})
    return r, etree.fromstring(r.data)


def send_set(client, kind, test_set=TEST_SET, xml=None):
    name, content = sample(kind)
    content = xml if xml is not None else content
    return post(client, "SendTestSetAsync", fileName=name.replace(".xml", ".zip"),
                contentFile=zip_b64(name, content), testSetId=test_set)


def zip_key_of(root):
    return root.xpath("//*[local-name()='ZipKey']")[0].text


def status(client, zip_key):
    r, root = post(client, "GetStatusZip", trackId=zip_key)
    return root.xpath("//*[local-name()='DianResponse']")


def val(node, name):
    r = node.xpath(f".//*[local-name()='{name}']")
    return (r[0].text or "") if r else ""


def all_text(node, name):
    return " | ".join(node.xpath(f".//*[local-name()='{name}']//text()"))


def test_full_test_set_flow_with_samples(client, store):
    store.set_settings({"need_credit_notes": "1", "need_debit_notes": "1"})
    for kind in ("invoice", "credit_note", "debit_note"):
        r, root = send_set(client, kind)
        assert r.status_code == 200
        zip_key = zip_key_of(root)
        assert zip_key
        resp = status(client, zip_key)
        assert len(resp) == 1
        assert val(resp[0], "StatusCode") == "00", all_text(resp[0], "ErrorMessage")
        assert val(resp[0], "IsValid") == "true"
        assert val(resp[0], "XmlDocumentKey") == uuid_of(kind)
        assert "SANDBOX NO OFICIAL" in val(resp[0], "StatusMessage")
    assert client.get("/api/progress").get_json()["complete"] is True


def test_default_progress_needs_two_notes(client):
    send_set(client, "invoice")
    send_set(client, "credit_note")
    send_set(client, "debit_note")
    progress = client.get("/api/progress").get_json()
    assert progress["complete"] is False
    assert {r["kind"]: (r["have"], r["need"]) for r in progress["rows"]} == {
        "invoice": (1, 1), "credit_note": (1, 2), "debit_note": (1, 2)}


def test_note_before_invoice_is_rejected(client):
    r, root = send_set(client, "credit_note")
    resp = status(client, zip_key_of(root))[0]
    assert val(resp, "StatusCode") == "99"
    assert "SBX-REF-002" in all_text(resp, "ErrorMessage")


def test_tampered_invoice_is_rejected(client):
    name, xml = sample("invoice")
    tampered = xml.replace(b'<cbc:PayableAmount currencyID="COP">238000.00', b'<cbc:PayableAmount currencyID="COP">138000.00', 1)
    assert tampered != xml
    r, root = send_set(client, "invoice", xml=tampered)
    resp = status(client, zip_key_of(root))[0]
    assert val(resp, "StatusCode") == "99"
    errors = all_text(resp, "ErrorMessage")
    assert "SBX-SIG-002" in errors and "SBX-CUFE-001" in errors


def test_any_change_after_signing_breaks_signature(client):
    name, xml = sample("invoice")
    tampered = xml.replace(b"Servicio de demostracion", b"Servicio alterado.......", 1)
    assert tampered != xml
    r, root = send_set(client, "invoice", xml=tampered)
    resp = status(client, zip_key_of(root))[0]
    assert "SBX-SIG-002" in all_text(resp, "ErrorMessage")


def test_duplicate_invoice_is_rejected(client):
    send_set(client, "invoice")
    r, root = send_set(client, "invoice")
    resp = status(client, zip_key_of(root))[0]
    assert val(resp, "StatusCode") == "99"
    assert "SBX-DUP-001" in all_text(resp, "ErrorMessage")


def test_wrong_test_set_id(client):
    r, root = send_set(client, "invoice", test_set="otro-id")
    assert not zip_key_of(root)
    assert "TestSetId" in all_text(root, "ErrorMessage")


def test_wrong_issuer_nit_rejected(client, store):
    store.set_settings({"issuer_nit": "800000000"})
    r, root = send_set(client, "invoice")
    resp = status(client, zip_key_of(root))[0]
    assert "SBX-NIT-001" in all_text(resp, "ErrorMessage")


def test_wrong_technical_key_rejected(client, store):
    store.set_settings({"technical_key": "f" * 40})
    r, root = send_set(client, "invoice")
    resp = status(client, zip_key_of(root))[0]
    assert "SBX-CUFE-001" in all_text(resp, "ErrorMessage")


def test_number_outside_range_rejected(client, store):
    store.replace_ranges([{"resolution": "1", "prefix": "SETP", "from_number": 1, "to_number": 10,
                           "valid_from": "2019-01-01", "valid_to": "2030-01-01", "technical_key": ""}])
    r, root = send_set(client, "invoice")
    resp = status(client, zip_key_of(root))[0]
    assert "SBX-NUM-001" in all_text(resp, "ErrorMessage")


def test_send_bill_sync_and_get_status(client):
    name, xml = sample("invoice")
    r, root = post(client, "SendBillSync", fileName="x.zip", contentFile=zip_b64(name, xml))
    assert val(root, "StatusCode") == "00"
    r, root = post(client, "GetStatus", trackId=uuid_of("invoice"))
    assert val(root, "StatusCode") == "00"
    r, root = post(client, "GetStatus", trackId="no-existe")
    assert val(root, "StatusCode") == "90"


def test_get_status_zip_unknown(client):
    resp = status(client, "no-existe")
    assert val(resp[0], "StatusCode") == "90"


def test_numbering_range(client):
    r, root = post(client, "GetNumberingRange", accountCode=META["issuer_nit"], accountCodeT="x", softwareCode="y")
    assert val(root, "OperationCode") == "100"
    assert val(root, "Prefix") == "SETP"
    assert val(root, "FromNumber") == "990000000"
    assert val(root, "TechnicalKey") == META["technical_key"]


def test_unknown_operation_and_bad_body(client):
    r, root = post(client, "NoExiste")
    assert r.status_code == 400
    r = client.post("/WcfDianCustomerServices.svc", data=b"no es xml")
    assert r.status_code == 400


def test_wsdl(client):
    r = client.get("/WcfDianCustomerServices.svc?wsdl")
    assert r.status_code == 200
    root = etree.fromstring(r.data)
    names = {n.get("name") for n in root.xpath("//*[local-name()='operation']")}
    assert {"SendTestSetAsync", "GetStatusZip", "GetNumberingRange"} <= names


def test_ui_pages_and_banner(client):
    for path in ("/", "/connect", "/documents", "/upload", "/settings", "/health", "/api/credentials"):
        r = client.get(path)
        assert r.status_code == 200, path
        if r.mimetype == "text/html":
            assert "SOLO DESARROLLO" in r.get_data(as_text=True)
    assert "no oficial" in client.get("/").headers["X-Sandbox"]


def test_upload_page_validates_xml(client):
    name, xml = sample("invoice")
    r = client.post("/upload", data={"files": (io.BytesIO(xml), name)}, content_type="multipart/form-data")
    assert r.status_code == 302
    page = client.get(r.headers["Location"])
    assert page.status_code == 200 and "Aceptado" in page.get_data(as_text=True)
    assert client.get(r.headers["Location"] + "/xml").status_code == 200


def test_certificate_download_opens_with_password(client):
    r = client.get("/connect/certificate.p12")
    assert r.status_code == 200
    key, cert, extra = pkcs12.load_key_and_certificates(r.data, b"sandbox")
    assert key is not None and "SANDBOX" in cert.subject.rfc4514_string()
    assert META["issuer_nit"] in cert.subject.rfc4514_string()


def test_credentials_api_shape(client):
    data = client.get("/api/credentials").get_json()
    for k in ("soap_url", "software_id", "software_pin", "test_set_id", "technical_key", "numbering_ranges",
              "certificate_url", "certificate_password", "issuer_nit"):
        assert k in data
    assert re.match(r"^\d{9}$", data["issuer_nit"])


def test_random_credentials_when_not_fixed(monkeypatch, tmp_path):
    monkeypatch.delenv("SANDBOX_FIXED_CREDENTIALS", raising=False)
    from sandbox.app import create_app
    a = create_app(str(tmp_path / "a"))
    b = create_app(str(tmp_path / "b"))
    sa = a.extensions["sandbox"]["store"].settings()
    sb = b.extensions["sandbox"]["store"].settings()
    assert sa["software_id"] != sb["software_id"] and len(sa["technical_key"]) == 40
    assert sa["test_set_id"] != sb["test_set_id"]
    a2 = create_app(str(tmp_path / "a"))  # reabrir la misma base conserva las credenciales
    assert a2.extensions["sandbox"]["store"].settings()["software_id"] == sa["software_id"]


def test_payroll_through_soap_and_progress(client, store):
    store.set_settings({"need_payrolls": "1", "need_invoices": "0", "need_credit_notes": "0", "need_debit_notes": "0"})
    name, xml = sample("payroll")
    r, root = post(client, "SendTestSetAsync", fileName="n.zip", contentFile=zip_b64(name, xml), testSetId=TEST_SET)
    resp = status(client, zip_key_of(root))[0]
    assert val(resp, "StatusCode") == "00", all_text(resp, "ErrorMessage")
    assert val(resp, "XmlDocumentKey") == ubl.parse(xml)[0].uuid
    progress = client.get("/api/progress").get_json()
    assert progress["complete"] and progress["rows"][-1]["kind"] == "payroll"


def test_payroll_duplicate_and_tampering(client):
    name, xml = sample("payroll")
    r, root = post(client, "SendTestSetAsync", fileName="n.zip", contentFile=zip_b64(name, xml), testSetId=TEST_SET)
    r, root = post(client, "SendTestSetAsync", fileName="n.zip", contentFile=zip_b64(name, xml), testSetId=TEST_SET)
    assert "SBX-DUP-001" in all_text(status(client, zip_key_of(root))[0], "ErrorMessage")
    tampered = xml.replace(b'Sueldo="2000000.00"', b'Sueldo="3000000.00"', 1)
    assert tampered != xml
    r, root = post(client, "SendBillSync", fileName="n.zip", contentFile=zip_b64(name, tampered))
    assert val(root, "StatusCode") == "99" and "SBX-SIG-002" in all_text(root, "ErrorMessage")


def test_readiness_and_rules_pages(client, store):
    store.set_settings({"need_credit_notes": "1", "need_debit_notes": "1"})
    for kind in ("invoice", "credit_note", "debit_note"):
        r, root = send_set(client, kind)
        status(client, zip_key_of(root))
    data = client.get("/api/readiness").get_json()
    checks = {c["key"]: c for c in data["checks"]}
    assert checks["set_invoice"]["ok"] and checks["status"]["ok"] and checks["signed"]["ok"]
    assert not checks["event"]["ok"] and checks["event"]["required"] is False
    for path in ("/readiness", "/rules"):
        assert client.get(path).status_code == 200
    assert "SBX-NOM-003" in client.get("/rules").get_data(as_text=True)


def test_resend_after_rejection_is_recorded(client, store):
    name, xml = sample("invoice")
    bad = xml.replace(b'<cbc:PayableAmount currencyID="COP">238000.00', b'<cbc:PayableAmount currencyID="COP">1.00', 1)
    send_set(client, "invoice", xml=bad)
    send_set(client, "invoice")
    checks = {c["key"]: c for c in client.get("/api/readiness").get_json()["checks"]}
    assert checks["resend"]["ok"] is True


def test_align_samples_route(client, store):
    store.set_settings({"software_id": "otro", "software_pin": "1", "technical_key": "k", "issuer_nit": "1"})
    assert client.post("/settings/align-samples").status_code == 302
    s = store.settings()
    assert s["software_id"] == META["software_id"] and s["issuer_nit"] == META["issuer_nit"]
