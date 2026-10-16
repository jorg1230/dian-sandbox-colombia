"""Lectura y validación de documentos electrónicos DIAN (UBL 2.1) para el simulador.

IMPORTANTE: las reglas de este módulo son un subconjunto propio, inspirado en las validaciones de la DIAN.
No son las reglas oficiales ni se mantienen al día con ellas. Los códigos empiezan por ``SBX-`` para que
nunca se confundan con los de la DIAN.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from lxml import etree

NS = {
    "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cn": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
    "dn": "urn:oasis:names:specification:ubl:schema:xsd:DebitNote-2",
    "ar": "urn:oasis:names:specification:ubl:schema:xsd:ApplicationResponse-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
    "sts": "dian:gov:co:facturaelectronica:Structures-2-1",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
    "nom": "dian:gov:co:facturaelectronica:NominaIndividual",
    "noma": "dian:gov:co:facturaelectronica:NominaIndividualDeAjuste",
}

KIND_LABELS = {
    "invoice": "Factura electrónica",
    "credit_note": "Nota crédito",
    "debit_note": "Nota débito",
    "support_document": "Documento soporte",
    "support_adjustment": "Nota de ajuste al documento soporte",
    "payroll": "Nómina electrónica",
    "payroll_adjustment": "Nómina electrónica de ajuste",
    "event": "Evento RADIAN",
}

EVENT_CODES = {
    "030": "Acuse de recibo de la factura",
    "031": "Reclamo de la factura",
    "032": "Recibo del bien o prestación del servicio",
    "033": "Aceptación expresa",
    "034": "Aceptación tácita",
    "035": "Aval",
}


@dataclass
class Finding:
    code: str
    message: str
    severity: str = "error"  # error | warning | info

    def as_dict(self):
        return {"code": self.code, "message": self.message, "severity": self.severity}


@dataclass
class Parsed:
    kind: str = ""
    number: str = ""
    uuid: str = ""
    uuid_scheme: str = ""
    issue_date: str = ""
    issue_time: str = ""
    type_code: str = ""
    environment: str = ""
    issuer_nit: str = ""
    issuer_dv: str = ""
    customer_id: str = ""
    line_extension: str = "0.00"
    payable: str = "0.00"
    tax_iva: str = "0.00"
    tax_inc: str = "0.00"
    tax_ica: str = "0.00"
    software_id: str = ""
    security_code: str = ""
    reference_number: str = ""
    reference_uuid: str = ""
    discrepancy_code: str = ""
    event_code: str = ""
    lines_total: str = "0.00"
    extra: dict = field(default_factory=dict)

    def as_dict(self):
        return self.__dict__.copy()


# ------------------------------------------------------------------ utilidades
def money(value) -> Decimal:
    try:
        return Decimal(str(value).strip() or "0").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return Decimal("0.00")


def fmt(value) -> str:
    return f"{money(value):.2f}"


def nit_check_digit(nit: str) -> str:
    """Dígito de verificación (módulo 11) de un NIT colombiano."""
    weights = [3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71]
    digits = "".join(c for c in nit if c.isdigit())
    total = sum(int(d) * weights[i] for i, d in enumerate(reversed(digits)))
    rest = total % 11
    return str(rest if rest < 2 else 11 - rest)


def _x(root, path):
    r = root.xpath(path, namespaces=NS)
    return r


def _text(root, path, default=""):
    r = _x(root, path)
    if not r:
        return default
    node = r[0]
    return (node if isinstance(node, str) else (node.text or "")).strip() or default


# --------------------------------------------------------------------- lectura
def parse(xml: bytes) -> tuple[Parsed | None, etree._Element | None, list[Finding]]:
    findings: list[Finding] = []
    try:
        root = etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True,
                                                            remove_blank_text=False, huge_tree=False))
    except etree.XMLSyntaxError as exc:
        return None, None, [Finding("SBX-XML-001", f"El archivo no es un XML bien formado: {exc}")]

    qn = etree.QName(root)
    p = Parsed()
    if qn.namespace == NS["inv"] and qn.localname == "Invoice":
        p.type_code = _text(root, "/inv:Invoice/cbc:InvoiceTypeCode")
        p.kind = "support_document" if p.type_code == "05" else "invoice"
        _common_ubl(root, p, "inv:Invoice")
        p.payable = fmt(_text(root, "/inv:Invoice/cac:LegalMonetaryTotal/cbc:PayableAmount", "0"))
        p.line_extension = fmt(_text(root, "/inv:Invoice/cac:LegalMonetaryTotal/cbc:LineExtensionAmount", "0"))
        lines = _x(root, "/inv:Invoice/cac:InvoiceLine/cbc:LineExtensionAmount")
    elif qn.namespace == NS["cn"] and qn.localname == "CreditNote":
        p.type_code = _text(root, "/cn:CreditNote/cbc:CreditNoteTypeCode", "91")
        p.kind = "support_adjustment" if p.type_code == "95" else "credit_note"
        _common_ubl(root, p, "cn:CreditNote")
        p.payable = fmt(_text(root, "/cn:CreditNote/cac:LegalMonetaryTotal/cbc:PayableAmount", "0"))
        p.line_extension = fmt(_text(root, "/cn:CreditNote/cac:LegalMonetaryTotal/cbc:LineExtensionAmount", "0"))
        lines = _x(root, "/cn:CreditNote/cac:CreditNoteLine/cbc:LineExtensionAmount")
    elif qn.namespace == NS["dn"] and qn.localname == "DebitNote":
        p.type_code = _text(root, "/dn:DebitNote/cbc:DebitNoteTypeCode", "92")
        p.kind = "debit_note"
        _common_ubl(root, p, "dn:DebitNote")
        p.payable = fmt(_text(root, "/dn:DebitNote/cac:RequestedMonetaryTotal/cbc:PayableAmount", "0"))
        p.line_extension = fmt(_text(root, "/dn:DebitNote/cac:RequestedMonetaryTotal/cbc:LineExtensionAmount", "0"))
        lines = _x(root, "/dn:DebitNote/cac:DebitNoteLine/cbc:LineExtensionAmount")
    elif qn.namespace == NS["ar"] and qn.localname == "ApplicationResponse":
        p.kind = "event"
        p.number = _text(root, "/ar:ApplicationResponse/cbc:ID")
        p.uuid = _text(root, "/ar:ApplicationResponse/cbc:UUID")
        p.issue_date = _text(root, "/ar:ApplicationResponse/cbc:IssueDate")
        p.issue_time = _text(root, "/ar:ApplicationResponse/cbc:IssueTime")
        p.environment = _text(root, "/ar:ApplicationResponse/cbc:ProfileExecutionID")
        p.event_code = _text(root, "//cac:DocumentResponse/cac:Response/cbc:ResponseCode")
        p.reference_uuid = _text(root, "//cac:DocumentResponse/cac:DocumentReference/cbc:UUID")
        p.reference_number = _text(root, "//cac:DocumentResponse/cac:DocumentReference/cbc:ID")
        p.issuer_nit = _text(root, "/ar:ApplicationResponse/cac:SenderParty/cac:PartyTaxScheme/cbc:CompanyID")
        p.issuer_dv = _text(root, "/ar:ApplicationResponse/cac:SenderParty/cac:PartyTaxScheme/cbc:CompanyID/@schemeID")
        return p, root, findings
    elif qn.namespace == NS["nom"] and qn.localname == "NominaIndividual":
        return _parse_payroll(root, p, "payroll", "nom:NominaIndividual"), root, findings
    elif qn.namespace == NS["noma"] and qn.localname == "NominaIndividualDeAjuste":
        return _parse_payroll(root, p, "payroll_adjustment", "noma:NominaIndividualDeAjuste"), root, findings
    else:
        return None, root, [Finding("SBX-DOC-001", f"Tipo de documento no reconocido: {{{qn.namespace}}}{qn.localname}")]

    p.lines_total = fmt(sum((money(n.text) for n in lines), Decimal("0")))
    return p, root, findings


def _common_ubl(root, p: Parsed, top: str):
    base = f"/{top}"
    p.number = _text(root, f"{base}/cbc:ID")
    p.uuid = _text(root, f"{base}/cbc:UUID")
    p.uuid_scheme = _text(root, f"{base}/cbc:UUID/@schemeName")
    p.issue_date = _text(root, f"{base}/cbc:IssueDate")
    p.issue_time = _text(root, f"{base}/cbc:IssueTime")
    p.environment = _text(root, f"{base}/cbc:ProfileExecutionID")
    sup = f"{base}/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID"
    p.issuer_nit = _text(root, sup)
    p.issuer_dv = _text(root, sup + "/@schemeID")
    p.customer_id = _text(root, f"{base}/cac:AccountingCustomerParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID")
    # El espacio de nombres de las extensiones DIAN difiere entre facturas y notas: se busca por nombre local.
    ext = "ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/*[local-name()='DianExtensions']"
    p.software_id = _text(root, f"{base}/{ext}/*[local-name()='SoftwareProvider']/*[local-name()='SoftwareID']")
    p.security_code = _text(root, f"{base}/{ext}/*[local-name()='SoftwareSecurityCode']")
    for code, attr in (("01", "tax_iva"), ("04", "tax_inc"), ("03", "tax_ica")):
        total = Decimal("0")
        for amt in _x(root, f"{base}/cac:TaxTotal/cac:TaxSubtotal[cac:TaxCategory/cac:TaxScheme/cbc:ID='{code}']"
                            "/cbc:TaxAmount"):
            total += money(amt.text)
        setattr(p, attr, fmt(total))
    p.reference_number = _text(root, f"{base}/cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID")
    p.reference_uuid = _text(root, f"{base}/cac:BillingReference/cac:InvoiceDocumentReference/cbc:UUID")
    p.discrepancy_code = _text(root, f"{base}/cac:DiscrepancyResponse/cbc:ResponseCode")


def _parse_payroll(root, p: Parsed, kind: str, top: str) -> Parsed:
    p.kind = kind
    pfx = top.split(":")[0]

    def P(path: str) -> str:
        """Antepone el prefijo del espacio de nombres a cada segmento (los hijos viven en el mismo espacio)."""
        segments = []
        for seg in path.strip("/").split("/"):
            segments.append(seg if seg.startswith("@") else f"{pfx}:{seg}")
        return f"/{top}/" + "/".join(segments)

    p.number = _text(root, P("NumeroSecuenciaXML/@Numero"))
    p.uuid = _text(root, P("InformacionGeneral/@CUNE"))
    p.uuid_scheme = _text(root, P("InformacionGeneral/@EncripCUNE"))
    p.issue_date = _text(root, P("InformacionGeneral/@FechaGen"))
    p.issue_time = _text(root, P("InformacionGeneral/@HoraGen"))
    p.environment = _text(root, P("InformacionGeneral/@Ambiente"))
    p.type_code = _text(root, P("InformacionGeneral/@TipoXML"))
    p.issuer_nit = _text(root, P("Empleador/@NIT"))
    p.issuer_dv = _text(root, P("Empleador/@DV"))
    p.customer_id = _text(root, P("Trabajador/@NumeroDocumento"))
    p.software_id = _text(root, P("ProveedorXML/@SoftwareID"))
    p.security_code = _text(root, P("ProveedorXML/@SoftwareSC"))
    p.line_extension = fmt(_text(root, P("DevengadosTotal"), "0"))
    p.payable = fmt(_text(root, P("ComprobanteTotal"), "0"))
    p.extra = {"devengados": fmt(_text(root, P("DevengadosTotal"), "0")),
               "deducciones": fmt(_text(root, P("DeduccionesTotal"), "0"))}
    return p


# ------------------------------------------------------------------------ CUFE
def cufe_preimage(p: Parsed, key: str) -> str:
    """Cadena que se hashea para el CUFE (facturas) o CUDE (notas, documento soporte)."""
    return "".join([
        p.number, p.issue_date, p.issue_time, p.line_extension,
        "01", p.tax_iva, "04", p.tax_inc, "03", p.tax_ica,
        p.payable, p.issuer_nit, p.customer_id or "222222222222", key, p.environment,
    ])


def compute_cufe(p: Parsed, technical_key: str, pin: str) -> tuple[str, str]:
    """Devuelve (hash SHA-384, tipo). Facturas usan la clave técnica; notas y documento soporte usan el PIN."""
    if p.kind == "invoice":
        key, label = technical_key, "CUFE"
    else:
        key, label = pin, "CUDE"
    return hashlib.sha384(cufe_preimage(p, key).encode("utf-8")).hexdigest(), label


def cune_preimage(p: Parsed, pin: str) -> str:
    """CUNE = SHA-384(NumNE + FecNE + HorNE + ValDev + ValDed + ValTolNE + NitNE + DocEmp + TipoXML + PIN + TipAmb)."""
    return "".join([p.number, p.issue_date, p.issue_time, p.extra.get("devengados", "0.00"),
                    p.extra.get("deducciones", "0.00"), p.payable, p.issuer_nit, p.customer_id, p.type_code, pin,
                    p.environment])


def compute_cune(p: Parsed, pin: str) -> str:
    return hashlib.sha384(cune_preimage(p, pin).encode("utf-8")).hexdigest()


def software_security_code(software_id: str, pin: str, number: str) -> str:
    return hashlib.sha384((software_id + pin + number).encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------ firma
_HASHES = {
    "sha1": hashes.SHA1, "sha256": hashes.SHA256, "sha384": hashes.SHA384, "sha512": hashes.SHA512,
}


def _hash_for(uri: str):
    m = re.search(r"(sha1|sha256|sha384|sha512)", uri or "")
    if not m:
        raise ValueError(f"algoritmo no soportado: {uri}")
    return _HASHES[m.group(1)]()


def _c14n(node, algorithm: str = "") -> bytes:
    exclusive = "exc-c14n" in (algorithm or "")
    return etree.tostring(node, method="c14n", exclusive=exclusive, with_comments="WithComments" in (algorithm or ""))


def _check_signature(root, sig) -> list[str]:
    """Verifica una ds:Signature (XAdES/xmldsig). Devuelve la lista de problemas (vacía = válida)."""
    problems: list[str] = []
    signed_info = sig.find("ds:SignedInfo", NS)
    sig_value = sig.find("ds:SignatureValue", NS)
    cert_nodes = sig.xpath(".//ds:X509Certificate", namespaces=NS)
    if signed_info is None or sig_value is None or not cert_nodes:
        return ["la firma está incompleta (SignedInfo, SignatureValue o X509Certificate)"]
    c14n_alg = signed_info.find("ds:CanonicalizationMethod", NS).get("Algorithm", "")
    method = signed_info.find("ds:SignatureMethod", NS).get("Algorithm", "")
    ids = {n.get("Id") or n.get("ID"): n for n in root.iter() if isinstance(n.tag, str) and (n.get("Id") or n.get("ID"))}
    for ref in signed_info.findall("ds:Reference", NS):
        uri = ref.get("URI", "")
        try:
            digest_alg = ref.find("ds:DigestMethod", NS).get("Algorithm", "")
            expected = base64.b64decode("".join((ref.find("ds:DigestValue", NS).text or "").split()))
            transforms = [t.get("Algorithm", "") for t in ref.findall("ds:Transforms/ds:Transform", NS)]
            if uri in ("", None):
                work = copy.deepcopy(root)
                pos = [i for i, s_ in enumerate(root.iter("{%s}Signature" % NS["ds"])) if s_ is sig][0]
                victim = list(work.iter("{%s}Signature" % NS["ds"]))[pos]
                victim.getparent().remove(victim)
                target = work
            elif uri.startswith("#"):
                target = ids.get(uri[1:])
                if target is None:
                    problems.append(f"la referencia {uri} apunta a un elemento que no existe")
                    continue
            else:
                problems.append(f"referencia externa no soportada: {uri}")
                continue
            c14n_t = next((t for t in transforms if "c14n" in t or "xml-exc" in t), c14n_alg)
            digest = hashes.Hash(_hash_for(digest_alg))
            digest.update(_c14n(target, c14n_t))
            if digest.finalize() != expected:
                problems.append(f"el resumen (digest) de la referencia '{uri or 'documento completo'}' no coincide: "
                                "el contenido cambió después de firmarse")
        except Exception as exc:  # referencia mal formada
            problems.append(f"no se pudo verificar la referencia '{uri}': {exc}")
    try:
        cert = x509.load_der_x509_certificate(base64.b64decode("".join((cert_nodes[0].text or "").split())))
        pub = cert.public_key()
        sig_bytes = base64.b64decode("".join((sig_value.text or "").split()))
        pub.verify(sig_bytes, _c14n(signed_info, c14n_alg), padding.PKCS1v15(), _hash_for(method))
    except InvalidSignature:
        problems.append("el valor de la firma (SignatureValue) no corresponde al certificado incluido")
    except Exception as exc:
        problems.append(f"no se pudo verificar SignatureValue: {exc}")
    return problems


def verify_signature(root) -> tuple[bool | None, dict, list[Finding]]:
    """Valida criptográficamente la firma XML (xmldsig/XAdES) usando el certificado que viaja en el documento.

    No se valida la cadena de confianza hasta una entidad certificadora real: eso solo lo hace la DIAN.
    """
    findings: list[Finding] = []
    info: dict = {}
    sigs = root.xpath("//ds:Signature", namespaces=NS)
    if not sigs:
        return False, info, [Finding("SBX-SIG-001", "El documento no está firmado (falta ds:Signature).")]
    cert_b64 = root.xpath("//ds:Signature//ds:X509Certificate/text()", namespaces=NS)
    if cert_b64:
        try:
            cert = x509.load_der_x509_certificate(base64.b64decode("".join(cert_b64[0].split())))
            info = {
                "subject": cert.subject.rfc4514_string(),
                "issuer": cert.issuer.rfc4514_string(),
                "serial": str(cert.serial_number),
                "not_before": cert.not_valid_before_utc.isoformat(),
                "not_after": cert.not_valid_after_utc.isoformat(),
            }
        except Exception as exc:
            findings.append(Finding("SBX-SIG-005", f"No se pudo leer el certificado de la firma: {exc}"))
    else:
        findings.append(Finding("SBX-SIG-005", "La firma no incluye el certificado (ds:X509Certificate)."))
    ok = True
    for sig in sigs:
        for problem in _check_signature(root, sig):
            ok = False
            findings.append(Finding("SBX-SIG-002", f"La firma digital no es válida: {problem}."))
    return ok, info, findings


def _parse_issue_dt(p: Parsed):
    try:
        return datetime.strptime(p.issue_date, "%Y-%m-%d").date()
    except ValueError:
        return None


# ------------------------------------------------------------------ validación
def validate(p: Parsed, root, ctx: dict) -> tuple[list[Finding], dict]:
    """Aplica las reglas del simulador. ``ctx`` trae settings, ranges y funciones del almacén."""
    s = ctx["settings"]
    findings: list[Finding] = []
    extra: dict = {}

    def flag(key):
        return s.get(key, "0") in ("1", "true", "on")

    # Fechas y ambiente
    d = _parse_issue_dt(p)
    if d is None:
        findings.append(Finding("SBX-DATE-002", f"Fecha de emisión inválida: '{p.issue_date}'."))
    elif d > date.today():
        findings.append(Finding("SBX-DATE-001", "La fecha de emisión es futura."))
    if flag("require_environment_2") and p.environment != "2":
        findings.append(Finding(
            "SBX-ENV-001", f"El simulador representa habilitación: el ambiente debe ser 2 (recibido '{p.environment}')."))

    # Emisor
    if p.issuer_nit:
        if p.issuer_dv and p.issuer_dv != nit_check_digit(p.issuer_nit):
            findings.append(Finding(
                "SBX-NIT-002", f"El dígito de verificación del emisor no coincide (esperado "
                               f"{nit_check_digit(p.issuer_nit)}, recibido {p.issuer_dv})."))
        if s.get("issuer_nit") and p.issuer_nit != s["issuer_nit"]:
            findings.append(Finding(
                "SBX-NIT-001", f"El NIT del emisor ({p.issuer_nit}) no es el registrado en el simulador "
                               f"({s['issuer_nit']})."))
    else:
        findings.append(Finding("SBX-NIT-003", "No se encontró el NIT del emisor."))

    # Firma
    if flag("verify_signature"):
        ok, info, sig_findings = verify_signature(root)
        findings += sig_findings
        extra["certificate"] = info
        if info and d:
            try:
                nb = datetime.fromisoformat(info["not_before"]).date()
                na = datetime.fromisoformat(info["not_after"]).date()
                if not (nb <= d <= na):
                    findings.append(Finding(
                        "SBX-SIG-003", f"El certificado no estaba vigente en la fecha de emisión ({nb} a {na})."))
            except (KeyError, ValueError):
                pass
        if info:
            findings.append(Finding(
                "SBX-SIG-004", "El simulador no valida que el certificado sea de una entidad certificadora "
                               "autorizada: eso solo lo verifica la DIAN real.", "info"))

    if p.kind in ("payroll", "payroll_adjustment", "event"):
        findings += _validate_non_ubl(p, ctx, root)
        return findings, extra

    # Software y código de seguridad
    if s.get("software_id") and p.software_id and p.software_id != s["software_id"]:
        findings.append(Finding(
            "SBX-SW-001", "El SoftwareID del documento no es el registrado en el simulador."))
    elif not p.software_id:
        findings.append(Finding("SBX-SW-003", "El documento no trae SoftwareID."))
    if p.software_id and s.get("software_pin"):
        expected = software_security_code(p.software_id, s["software_pin"], p.number)
        if p.security_code != expected:
            findings.append(Finding(
                "SBX-SW-002", "El SoftwareSecurityCode no corresponde a SoftwareID + PIN + número del documento."))

    # CUFE / CUDE
    if flag("verify_cufe"):
        range_key = _range_key(p, ctx)
        key = range_key if p.kind == "invoice" else s.get("software_pin", "")
        if not key:
            findings.append(Finding("SBX-CUFE-002", "No hay clave técnica/PIN configurados: no se verificó el CUFE.",
                                    "warning"))
        else:
            expected, label = compute_cufe(p, key, s.get("software_pin", ""))
            extra["expected_uuid"] = expected
            if p.uuid.lower() != expected:
                findings.append(Finding(
                    "SBX-CUFE-001", f"El {label} del documento no coincide con el calculado por el simulador."))

    # Numeración
    if p.kind == "invoice":
        findings += _validate_numbering(p, ctx)

    # Totales
    if flag("verify_totals"):
        if money(p.lines_total) != money(p.line_extension):
            findings.append(Finding(
                "SBX-TOT-001", f"La suma de las líneas ({p.lines_total}) no coincide con LineExtensionAmount "
                               f"({p.line_extension})."))

    # Notas
    if p.kind in ("credit_note", "debit_note", "support_adjustment"):
        if not p.discrepancy_code:
            findings.append(Finding("SBX-NC-001", "La nota no trae el concepto de corrección (DiscrepancyResponse)."))
        if not p.reference_number and not p.reference_uuid:
            findings.append(Finding("SBX-REF-001", "La nota no referencia el documento que corrige (BillingReference)."))
        elif not flag("allow_external_references"):
            found = (ctx["accepted_by_uuid"](p.reference_uuid) if p.reference_uuid else None) or \
                    (ctx["accepted_by_number"](p.reference_number) if p.reference_number else None)
            if not found:
                findings.append(Finding(
                    "SBX-REF-002", "El documento referenciado no existe entre los aceptados por el simulador "
                                   "(activa 'permitir referencias externas' si viene de otro sistema)."))

    # Paquete de reglas "filtro DIAN" (estructura, partes, impuestos, pago, fechas, QR, moneda, notas, ítems)
    if flag("dian_filter"):
        from . import dian_rules  # import tardío: dian_rules importa este módulo

        findings += dian_rules.validate(p, root, s)

    # Duplicado
    prior = ctx["accepted_by_number"](p.number) if p.number else None
    if prior:
        findings.append(Finding("SBX-DUP-001", f"El documento {p.number} ya fue aceptado antes (duplicado)."))
    return findings, extra


def _range_key(p: Parsed, ctx: dict) -> str:
    for r in ctx["ranges"]:
        pref = r.get("prefix") or ""
        if pref and p.number.startswith(pref) and r.get("technical_key"):
            return r["technical_key"]
    return ctx["settings"].get("technical_key", "")


def _validate_numbering(p: Parsed, ctx: dict) -> list[Finding]:
    ranges = ctx["ranges"]
    if not ranges:
        return []
    for r in ranges:
        pref = r.get("prefix") or ""
        if pref and not p.number.startswith(pref):
            continue
        digits = p.number[len(pref):]
        if not digits.isdigit():
            continue
        n = int(digits)
        if int(r["from_number"]) <= n <= int(r["to_number"]):
            d = _parse_issue_dt(p)
            vf, vt = r.get("valid_from") or "", r.get("valid_to") or ""
            if d and vf and str(d) < vf:
                return [Finding("SBX-NUM-002", f"La fecha del documento es anterior al inicio de la resolución ({vf}).")]
            if d and vt and str(d) > vt:
                return [Finding("SBX-NUM-002", f"La fecha del documento es posterior al fin de la resolución ({vt}).")]
            return []
    return [Finding("SBX-NUM-001", f"El número {p.number} no está en ningún rango de numeración autorizado.")]


def _validate_non_ubl(p: Parsed, ctx: dict, root) -> list[Finding]:
    findings: list[Finding] = []
    s = ctx["settings"]
    if p.kind == "event":
        if p.event_code not in EVENT_CODES:
            findings.append(Finding("SBX-EVT-001", f"Código de evento desconocido: '{p.event_code}'."))
        if not p.reference_uuid and not p.reference_number:
            findings.append(Finding("SBX-EVT-002", "El evento no referencia ninguna factura."))
        elif s.get("allow_external_references", "0") not in ("1", "true", "on"):
            found = (ctx["accepted_by_uuid"](p.reference_uuid) if p.reference_uuid else None) or \
                    (ctx["accepted_by_number"](p.reference_number) if p.reference_number else None)
            if not found:
                findings.append(Finding("SBX-EVT-003", "La factura del evento no existe entre las aceptadas."))
    else:
        if not p.uuid:
            findings.append(Finding("SBX-CUNE-001", "La nómina no trae CUNE."))
        elif s.get("verify_cufe", "0") in ("1", "true", "on"):
            if not s.get("software_pin"):
                findings.append(Finding("SBX-CUNE-003", "No hay PIN configurado: no se verificó el CUNE.", "warning"))
            elif p.uuid.lower() != compute_cune(p, s["software_pin"]):
                findings.append(Finding("SBX-CUNE-001", "El CUNE de la nómina no coincide con el calculado por el simulador."))
        if s.get("software_id") and p.software_id and p.software_id != s["software_id"]:
            findings.append(Finding("SBX-SW-001", "El SoftwareID del documento no es el registrado en el simulador."))
        if p.software_id and s.get("software_pin") and p.security_code != software_security_code(
                p.software_id, s["software_pin"], p.number):
            findings.append(Finding("SBX-SW-002", "El SoftwareSC no corresponde a SoftwareID + PIN + número del documento."))
        if s.get("dian_filter", "0") in ("1", "true", "on"):
            from . import dian_rules

            findings += dian_rules.validate_payroll(p, root)
    if p.number and ctx["accepted_by_number"](p.number):
        findings.append(Finding("SBX-DUP-001", f"El documento {p.number} ya fue aceptado antes (duplicado)."))
    return findings


def is_accepted(findings: list[Finding]) -> bool:
    return not any(f.severity == "error" for f in findings)
