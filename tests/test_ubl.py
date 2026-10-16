import pytest

from sandbox import ubl
from tests.conftest import META, sample


@pytest.mark.parametrize("kind", ["invoice", "credit_note", "debit_note"])
def test_cufe_formula_matches_real_module_output(kind):
    name, xml = sample(kind)
    parsed, root, findings = ubl.parse(xml)
    assert not findings
    key = META["technical_key"]
    expected, label = ubl.compute_cufe(parsed, key, META["pin"])
    assert expected == parsed.uuid, f"{label} no coincide: {ubl.cufe_preimage(parsed, key if kind == 'invoice' else META['pin'])}"


@pytest.mark.parametrize("kind", ["invoice", "credit_note", "debit_note"])
def test_parse_basic_fields(kind):
    name, xml = sample(kind)
    parsed, root, _ = ubl.parse(xml)
    assert parsed.kind == kind
    assert parsed.issuer_nit == META["issuer_nit"]
    assert parsed.software_id == META["software_id"]
    assert parsed.environment == "2"
    assert ubl.money(parsed.lines_total) == ubl.money(parsed.line_extension)


def test_nit_check_digit():
    assert ubl.nit_check_digit(META["issuer_nit"]) == META["issuer_dv"]
    assert ubl.nit_check_digit("900123456") == "8"


def test_malformed_xml():
    parsed, root, findings = ubl.parse(b"<no cierra")
    assert parsed is None and findings[0].code == "SBX-XML-001"


def test_unknown_document():
    parsed, root, findings = ubl.parse(b"<Algo xmlns='urn:x'/>")
    assert parsed is None and findings[0].code == "SBX-DOC-001"


def test_signature_of_sample_is_valid():
    name, xml = sample("invoice")
    parsed, root, _ = ubl.parse(xml)
    ok, info, findings = ubl.verify_signature(root)
    assert ok is True, findings
    assert "subject" in info
