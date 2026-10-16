"""Cada regla del simulador se prueba alterando un documento válido (generado por Odoo + el módulo OCA)."""
import pytest
from lxml import etree

from sandbox import dian_rules, ubl
from tests.conftest import META, sample

NS = ubl.NS
BASE_SETTINGS = {
    "software_id": META["software_id"], "software_pin": META["pin"], "technical_key": META["technical_key"],
    "issuer_nit": META["issuer_nit"], "verify_signature": "0", "verify_cufe": "0", "verify_totals": "1",
    "allow_external_references": "1", "require_environment_2": "1", "dian_filter": "1", "uvt_value": "49799",
    "max_age_days": "0",
}


def findings_for(kind, mutate, settings=None, **flags):
    name, xml = sample(kind)
    root = etree.fromstring(xml)
    mutate(root)
    xml2 = etree.tostring(root)
    s = {**BASE_SETTINGS, **(settings or {})}
    parsed, root2, f = ubl.parse(xml2)
    assert parsed is not None, f
    ctx = {"settings": s, "ranges": [], "accepted_by_number": lambda n: None, "accepted_by_uuid": lambda u: None}
    more, _ = ubl.validate(parsed, root2, ctx)
    return {x.code: x for x in f + more}


def x(root, path):
    return root.xpath(path, namespaces=NS)


def set_text(path, value):
    def m(root):
        x(root, path)[0].text = value
    return m


def set_attr(path, attr, value):
    def m(root):
        x(root, path)[0].set(attr, value)
    return m


def remove(path):
    def m(root):
        for n in x(root, path):
            n.getparent().remove(n)
    return m


SUP = "//cac:AccountingSupplierParty/cac:Party"
CUS = "//cac:AccountingCustomerParty/cac:Party"

def ln(name):
    return f"//*[local-name()='{name}']"


def set_local_attr(name, attr, value):
    def m(root):
        root.xpath(ln(name))[0].set(attr, value)
    return m


def set_local_text(name, value):
    def m(root):
        root.xpath(ln(name))[0].text = value
    return m


def remove_local(name):
    def m(root):
        for n in root.xpath(ln(name)):
            n.getparent().remove(n)
    return m


CASES = [
    # (código esperado, tipo de documento, mutación, ajustes extra)
    ("SBX-STR-003", "invoice", set_text("//cbc:UBLVersionID", "UBL 2.0"), {}),
    ("SBX-STR-004", "invoice", remove("//cbc:ProfileID"), {}),
    ("SBX-PAR-001", "invoice", remove(SUP + "/cac:PartyTaxScheme/cbc:TaxLevelCode"), {}),
    ("SBX-PAR-002", "invoice", set_text(CUS + "/cac:PartyTaxScheme/cbc:CompanyID", "222222222222"), {"uvt_value": "1000"}),
    ("SBX-PAR-003", "invoice", set_attr(CUS + "/cac:PartyTaxScheme/cbc:CompanyID", "schemeID", "9"), {}),
    ("SBX-PAR-004", "invoice", set_attr(SUP + "/cac:PartyTaxScheme/cbc:CompanyID", "schemeName", "99"), {}),
    ("SBX-PAR-005", "invoice", lambda r: [n.getparent().remove(n) for n in x(r, CUS + "//cbc:RegistrationName")], {}),
    ("SBX-IMP-002", "invoice", set_text("//cac:TaxTotal/cac:TaxSubtotal/cbc:TaxAmount", "100.00"), {}),
    ("SBX-IMP-001", "invoice", set_text("//cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:Percent", "16.00"), {}),
    ("SBX-PAG-001", "invoice", remove("//cac:PaymentMeans"), {}),
    ("SBX-PAG-002", "invoice", lambda r: (set_text("//cac:PaymentMeans/cbc:ID", "2")(r), remove("//cac:PaymentMeans/cbc:PaymentDueDate")(r)), {}),
    ("SBX-FEC-002", "invoice", set_text("//cbc:IssueTime", "10:25:18+00:00"), {}),
    ("SBX-FEC-003", "invoice", set_text("//cbc:IssueDate", "2020-01-01"), {"max_age_days": "1"}),
    ("SBX-QR-001", "invoice", lambda r: [n.getparent().remove(n) for n in r.xpath("//*[local-name()='QRCode']")], {}),
    ("SBX-MON-001", "invoice", set_text("//cbc:DocumentCurrencyCode", "USD"), {}),
    ("SBX-NC-003", "credit_note", set_text("//cac:DiscrepancyResponse/cbc:ResponseCode", "9"), {}),
    ("SBX-NC-003", "debit_note", set_text("//cac:DiscrepancyResponse/cbc:ResponseCode", "5"), {}),
    ("SBX-NC-001", "credit_note", remove("//cac:DiscrepancyResponse"), {}),
    ("SBX-REF-001", "credit_note", remove("//cac:BillingReference"), {}),
    ("SBX-ITM-001", "invoice", set_text("//cac:InvoiceLine/cbc:InvoicedQuantity", "0"), {}),
    ("SBX-ITM-002", "invoice", remove("//cac:InvoiceLine/cac:Item/cac:StandardItemIdentification"), {}),
    ("SBX-NIT-002", "invoice", set_attr(SUP + "/cac:PartyTaxScheme/cbc:CompanyID", "schemeID", "9"), {}),
    ("SBX-NIT-001", "invoice", lambda r: None, {"issuer_nit": "800000000"}),
    ("SBX-SW-001", "invoice", lambda r: None, {"software_id": "otro-software"}),
    ("SBX-SW-002", "invoice", lambda r: None, {"software_pin": "99999"}),
    ("SBX-ENV-001", "invoice", set_text("//cbc:ProfileExecutionID", "1"), {}),
    ("SBX-DATE-001", "invoice", set_text("//cbc:IssueDate", "2999-01-01"), {}),
    ("SBX-TOT-001", "invoice", set_text("//cac:LegalMonetaryTotal/cbc:LineExtensionAmount", "1.00"), {}),
    ("SBX-CUFE-001", "invoice", set_text("//cbc:UUID", "0" * 96), {"verify_cufe": "1"}),
    ("SBX-SIG-001", "invoice", remove("//ds:Signature"), {"verify_signature": "1"}),
    ("SBX-SIG-002", "invoice", set_text("//cbc:Note", "alterado"), {"verify_signature": "1"}),
    ("SBX-SIG-003", "invoice", set_text("//cbc:IssueDate", "2000-01-01"), {"verify_signature": "1"}),
    # nómina electrónica
    ("SBX-NOM-003", "payroll", set_local_text("ComprobanteTotal", "1.00"), {}),
    ("SBX-NOM-004", "payroll", set_local_text("DevengadosTotal", "9999999.00"), {}),
    ("SBX-NOM-005", "payroll", set_local_attr("Periodo", "FechaLiquidacionFin", "2025-01-01"), {}),
    ("SBX-NOM-006", "payroll", lambda r: r.xpath(ln("Trabajador"))[0].attrib.pop("PrimerNombre"), {}),
    ("SBX-NOM-007", "payroll", set_local_attr("Basico", "SueldoTrabajado", "0.00"), {}),
    ("SBX-NOM-008", "payroll", remove_local("Salud"), {}),
    ("SBX-NOM-009", "payroll", set_local_attr("InformacionGeneral", "TipoXML", "999"), {}),
    ("SBX-NOM-010", "payroll", set_local_attr("InformacionGeneral", "HoraGen", "10:43:20+00:00"), {}),
    ("SBX-CUNE-001", "payroll", set_local_attr("InformacionGeneral", "CUNE", "0" * 96), {"verify_cufe": "1"}),
    ("SBX-SW-002", "payroll", lambda r: None, {"software_pin": "99999"}),
    ("SBX-SIG-002", "payroll", set_local_attr("Pago", "Forma", "2"), {"verify_signature": "1"}),
    ("SBX-DOC-001", None, None, {}),
]


@pytest.mark.parametrize("code,kind,mutation,extra", [c for c in CASES if c[1]],
                         ids=[f"{c[0]}-{c[1]}" for c in CASES if c[1]])
def test_rule_detects_problem(code, kind, mutation, extra):
    found = findings_for(kind, mutation, extra)
    assert code in found, f"{code} no se detectó; hallazgos: {sorted(found)}"


@pytest.mark.parametrize("kind", ["invoice", "credit_note", "debit_note", "payroll"])
def test_unmodified_documents_have_no_errors(kind):
    found = findings_for(kind, lambda r: None, {"verify_signature": "1", "verify_cufe": "1"})
    errors = {c: f.message for c, f in found.items() if f.severity == "error"}
    assert not errors, errors


def test_every_rule_in_catalog_is_covered_by_a_test():
    tested = {c[0] for c in CASES}
    missing = [c for c in dian_rules.RULES if c not in tested]
    assert not missing, f"reglas sin prueba: {missing}"


def test_rule_catalog_shape():
    for code, (family, severity, desc, ref) in dian_rules.RULES.items():
        assert code.startswith("SBX-") and severity in ("error", "warning") and desc and family and ref


def test_payroll_sum_counts_simple_elements_and_attributes():
    """Las deducciones pueden venir como atributos (Salud) o como elementos simples (RetencionFuente)."""
    section = etree.fromstring(
        '<Deducciones xmlns="x"><Salud Porcentaje="4.00" Deduccion="80000.00"/><FondoPension Porcentaje="4.00" '
        'Deduccion="80000.00"/><RetencionFuente>1124000.00</RetencionFuente><AFC>5000.00</AFC></Deducciones>')
    assert dian_rules._sum_money(section) == dian_rules.Decimal("1289000.00")
