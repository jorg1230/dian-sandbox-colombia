"""Reglas de "filtro DIAN" del simulador: estructura, partes, impuestos, pago, fechas, QR, moneda, notas e ítems.

NO son las reglas oficiales de validación de la DIAN. Son comprobaciones propias, pensadas a partir de los
requisitos públicos del Anexo Técnico de factura electrónica, para que el software contable detecte temprano los
errores más comunes. Cada regla indica su familia y una referencia orientativa; la fuente de verdad es siempre
la normativa vigente de la DIAN (https://micrositios.dian.gov.co/sistema-de-facturacion-electronica/).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from lxml import etree

from . import ubl
from .ubl import NS, Finding, Parsed, money, nit_check_digit

# código -> (familia, severidad por defecto, descripción, referencia orientativa)
RULES: dict[str, tuple[str, str, str, str]] = {
    "SBX-STR-003": ("Estructura", "error", "UBLVersionID debe ser 'UBL 2.1'.", "Anexo técnico, formato UBL 2.1"),
    "SBX-STR-004": ("Estructura", "warning", "Falta ProfileID del documento.", "Anexo técnico"),
    "SBX-PAR-001": ("Partes", "error", "El emisor debe informar sus responsabilidades fiscales (TaxLevelCode).",
                    "Anexo técnico; RUT (responsabilidades)"),
    "SBX-PAR-002": ("Partes", "error", "El adquirente debe estar identificado; el consumidor final (222222222222) "
                                       "solo aplica por debajo del tope en UVT configurado.", "Estatuto Tributario art. 617"),
    "SBX-PAR-003": ("Partes", "error", "El dígito de verificación del NIT del adquirente no coincide.", "Anexo técnico"),
    "SBX-PAR-004": ("Partes", "error", "Tipo de documento del emisor no reconocido.", "Anexo técnico, tabla de tipos de documento"),
    "SBX-PAR-005": ("Partes", "error", "Falta el nombre o razón social del emisor o del adquirente.", "Estatuto Tributario art. 617"),
    "SBX-IMP-001": ("Impuestos", "warning", "Tarifa de IVA fuera de las habituales (0, 5, 19).", "Estatuto Tributario, IVA"),
    "SBX-IMP-002": ("Impuestos", "error", "El valor del impuesto no corresponde a base × tarifa (tolerancia $1).", "Anexo técnico"),
    "SBX-PAG-001": ("Pago", "error", "Falta la forma/medio de pago (PaymentMeans).", "Anexo técnico"),
    "SBX-PAG-002": ("Pago", "error", "Pago a crédito sin fecha de vencimiento (PaymentDueDate).", "Anexo técnico"),
    "SBX-FEC-002": ("Fechas", "error", "La hora debe llevar la zona horaria de Colombia (-05:00).", "Anexo técnico"),
    "SBX-FEC-003": ("Fechas", "error", "El documento supera la antigüedad máxima permitida por el simulador.", "Configurable"),
    "SBX-QR-001": ("QR", "error", "Falta el código QR del documento.", "Anexo técnico"),
    "SBX-MON-001": ("Moneda", "error", "Moneda distinta de COP sin tasa de cambio (PaymentExchangeRate).", "Anexo técnico"),
    "SBX-NC-003": ("Notas", "error", "Concepto de corrección fuera de la tabla (NC 1-6, ND 1-4).", "Anexo técnico"),
    "SBX-ITM-001": ("Ítems", "error", "Cada línea requiere descripción, cantidad mayor que cero y precio no negativo.",
                    "Estatuto Tributario art. 617"),
    "SBX-ITM-002": ("Ítems", "warning", "La línea no trae código de producto (StandardItemIdentification).", "Anexo técnico"),
}


def _t(root, path):
    r = root.xpath(path, namespaces=NS)
    if not r:
        return ""
    n = r[0]
    return (str(n) if isinstance(n, str) else (n.text or "")).strip()


def _f(code: str, message: str | None = None) -> Finding:
    fam, sev, desc, ref = RULES[code]
    return Finding(code, message or desc, sev)


def validate(p: Parsed, root, settings: dict) -> list[Finding]:
    """Aplica el paquete de reglas a facturas, notas y documento soporte (UBL)."""
    out: list[Finding] = []
    top = {"invoice": "inv:Invoice", "support_document": "inv:Invoice", "credit_note": "cn:CreditNote",
           "support_adjustment": "cn:CreditNote", "debit_note": "dn:DebitNote"}.get(p.kind)
    if not top:
        return out
    base = f"/{top}"

    # Estructura
    if _t(root, f"{base}/cbc:UBLVersionID") != "UBL 2.1":
        out.append(_f("SBX-STR-003"))
    if not _t(root, f"{base}/cbc:ProfileID"):
        out.append(_f("SBX-STR-004"))

    # Partes
    sup = f"{base}/cac:AccountingSupplierParty/cac:Party"
    cus = f"{base}/cac:AccountingCustomerParty/cac:Party"
    if not _t(root, f"{sup}/cac:PartyTaxScheme/cbc:TaxLevelCode"):
        out.append(_f("SBX-PAR-001"))
    if p.kind not in ("support_document",):
        if not _t(root, f"{sup}/cac:PartyTaxScheme/cbc:RegistrationName") and not _t(root, f"{sup}/cac:PartyLegalEntity/cbc:RegistrationName"):
            out.append(_f("SBX-PAR-005", "Falta el nombre o razón social del emisor."))
    if not _t(root, f"{cus}/cac:PartyTaxScheme/cbc:RegistrationName") and not _t(root, f"{cus}/cac:PartyLegalEntity/cbc:RegistrationName"):
        out.append(_f("SBX-PAR-005", "Falta el nombre o razón social del adquirente."))
    if not p.customer_id:
        out.append(_f("SBX-PAR-002", "El documento no identifica al adquirente."))
    elif p.customer_id == "222222222222":
        try:
            uvt = Decimal(settings.get("uvt_value") or "0")
        except Exception:
            uvt = Decimal("0")
        limit = uvt * 5
        if uvt and money(p.payable) > limit:
            out.append(_f("SBX-PAR-002", f"Venta a consumidor final (222222222222) por {p.payable}, superior a 5 UVT "
                                          f"({limit}). Debe identificarse al adquirente."))
    cus_scheme = _t(root, f"{cus}/cac:PartyTaxScheme/cbc:CompanyID/@schemeName")
    cus_dv = _t(root, f"{cus}/cac:PartyTaxScheme/cbc:CompanyID/@schemeID")
    if cus_scheme == "31" and p.customer_id and cus_dv and cus_dv != nit_check_digit(p.customer_id):
        out.append(_f("SBX-PAR-003"))
    sup_scheme = _t(root, f"{sup}/cac:PartyTaxScheme/cbc:CompanyID/@schemeName")
    if sup_scheme and sup_scheme not in {"11", "12", "13", "21", "22", "31", "41", "42", "43", "47", "50", "91"}:
        out.append(_f("SBX-PAR-004"))

    # Impuestos (a nivel documento)
    for sub in root.xpath(f"{base}/cac:TaxTotal/cac:TaxSubtotal", namespaces=NS):
        scheme = _t(sub, "cac:TaxCategory/cac:TaxScheme/cbc:ID")
        pct = _t(sub, "cac:TaxCategory/cbc:Percent")
        taxable, amount = _t(sub, "cbc:TaxableAmount"), _t(sub, "cbc:TaxAmount")
        if pct and taxable:
            expected = money(Decimal(taxable) * Decimal(pct) / 100)
            if abs(expected - money(amount)) > Decimal("1.00"):
                out.append(_f("SBX-IMP-002", f"Impuesto {scheme}: base {taxable} × {pct}% = {expected}, "
                                              f"pero el documento informa {amount}."))
        if scheme == "01" and pct and Decimal(pct) not in (Decimal("0"), Decimal("5"), Decimal("19")):
            out.append(_f("SBX-IMP-001", f"Tarifa de IVA inusual: {pct}%."))

    # Pago
    if p.kind != "debit_note" or root.xpath(f"{base}/cac:PaymentMeans", namespaces=NS):
        pm = root.xpath(f"{base}/cac:PaymentMeans", namespaces=NS)
        if not pm:
            out.append(_f("SBX-PAG-001"))
        else:
            form = _t(pm[0], "cbc:ID")
            if not _t(pm[0], "cbc:PaymentMeansCode"):
                out.append(_f("SBX-PAG-001"))
            if form == "2" and not _t(pm[0], "cbc:PaymentDueDate"):
                out.append(_f("SBX-PAG-002"))

    # Fechas
    if p.issue_time and not p.issue_time.endswith("-05:00"):
        out.append(_f("SBX-FEC-002", f"La hora '{p.issue_time}' no lleva el offset -05:00 de Colombia."))
    try:
        max_age = int(settings.get("max_age_days") or 0)
    except ValueError:
        max_age = 0
    if max_age:
        try:
            age = (date.today() - datetime.strptime(p.issue_date, "%Y-%m-%d").date()).days
            if age > max_age:
                out.append(_f("SBX-FEC-003", f"El documento tiene {age} días de antigüedad (máximo {max_age})."))
        except ValueError:
            pass

    # QR
    if not root.xpath("//*[local-name()='QRCode']/text()"):
        out.append(_f("SBX-QR-001"))

    # Moneda
    currency = _t(root, f"{base}/cbc:DocumentCurrencyCode")
    if currency and currency != "COP" and not root.xpath(f"{base}/cac:PaymentExchangeRate", namespaces=NS):
        out.append(_f("SBX-MON-001"))

    # Notas
    if p.kind in ("credit_note", "debit_note", "support_adjustment") and p.discrepancy_code:
        valid = {"credit_note": set("123456"), "support_adjustment": set("12345"), "debit_note": set("1234")}[p.kind]
        if p.discrepancy_code not in valid:
            out.append(_f("SBX-NC-003", f"Concepto de corrección '{p.discrepancy_code}' no válido para este documento."))

    # Ítems
    line_tag = {"inv:Invoice": "InvoiceLine", "cn:CreditNote": "CreditNoteLine", "dn:DebitNote": "DebitNoteLine"}[top]
    qty_tag = {"InvoiceLine": "InvoicedQuantity", "CreditNoteLine": "CreditedQuantity", "DebitNoteLine": "DebitedQuantity"}[line_tag]
    bad_lines = []
    no_code = []
    for i, line in enumerate(root.xpath(f"{base}/cac:{line_tag}", namespaces=NS), 1):
        qty = _t(line, f"cbc:{qty_tag}")
        price = _t(line, "cac:Price/cbc:PriceAmount")
        desc = _t(line, "cac:Item/cbc:Description")
        try:
            ok = bool(desc) and Decimal(qty or "0") > 0 and Decimal(price or "0") >= 0
        except Exception:
            ok = False
        if not ok:
            bad_lines.append(str(i))
        if not _t(line, "cac:Item/cac:StandardItemIdentification/cbc:ID"):
            no_code.append(str(i))
    if bad_lines:
        out.append(_f("SBX-ITM-001", f"Líneas con datos incompletos o inválidos: {', '.join(bad_lines)}."))
    if no_code:
        out.append(_f("SBX-ITM-002", f"Líneas sin código de producto: {', '.join(no_code)}."))
    return out


# --------------------------------------------------------------------------------------------- nómina
RULES.update({
    "SBX-NOM-003": ("Nómina", "error", "ComprobanteTotal debe ser DevengadosTotal − DeduccionesTotal.", "Anexo técnico nómina electrónica"),
    "SBX-NOM-004": ("Nómina", "error", "DevengadosTotal / DeduccionesTotal no coinciden con la suma de los conceptos.", "Anexo técnico nómina electrónica"),
    "SBX-NOM-005": ("Nómina", "error", "Fechas del periodo incoherentes (ingreso, inicio y fin de liquidación).", "Anexo técnico nómina electrónica"),
    "SBX-NOM-006": ("Nómina", "error", "Datos del trabajador incompletos (tipo y número de documento, apellido, nombre).", "Anexo técnico nómina electrónica"),
    "SBX-NOM-007": ("Nómina", "error", "Falta el devengado básico (Basico/SueldoTrabajado) o el sueldo es cero.", "Anexo técnico nómina electrónica"),
    "SBX-NOM-008": ("Nómina", "error", "Las deducciones obligatorias de salud y fondo de pensión son requeridas.", "Anexo técnico nómina electrónica"),
    "SBX-NOM-009": ("Nómina", "error", "TipoXML inválido (102 individual, 103 ajuste) o ajuste sin predecesor.", "Anexo técnico nómina electrónica"),
    "SBX-NOM-010": ("Nómina", "error", "La hora de generación debe llevar el offset -05:00 de Colombia.", "Anexo técnico nómina electrónica"),
})

_NON_MONEY = ("Fecha", "Hora", "Cantidad", "Porcentaje", "Dias", "Tipo", "Descripcion", "Codigo", "Concepto", "Nombre",
              "Tiempo", "Id", "Numero", "Pais", "Departamento", "Municipio", "Direccion")


def _num(value):
    try:
        return Decimal(str(value).strip())
    except Exception:
        return None


def _sum_money(section) -> Decimal:
    """Suma los importes de una sección de nómina: atributos monetarios (Pago, Deduccion…) y elementos simples
    con valor numérico (RetencionFuente, AFC, Dotacion…)."""
    total = Decimal("0")
    if section is None:
        return total
    for el in section.iter():
        if not isinstance(el.tag, str):
            continue
        if len(el) == 0 and el is not section:  # elemento simple con importe en el texto
            number = _num(el.text) if el.text and el.text.strip() else None
            if number is not None and not any(k in etree.QName(el).localname for k in _NON_MONEY):
                total += number
        for name, value in el.attrib.items():
            if any(prefix in name for prefix in _NON_MONEY):
                continue
            number = _num(value)
            if number is not None:
                total += number
    return total


def validate_payroll(p: Parsed, root) -> list[Finding]:
    out: list[Finding] = []
    def one(local):
        r = root.xpath(f"/*/*[local-name()='{local}']")
        return r[0] if r else None

    dev, ded, total = one("DevengadosTotal"), one("DeduccionesTotal"), one("ComprobanteTotal")
    d_dev = money((dev.text if dev is not None else "0") or "0")
    d_ded = money((ded.text if ded is not None else "0") or "0")
    d_tot = money((total.text if total is not None else "0") or "0")
    if d_dev - d_ded != d_tot:
        out.append(_f("SBX-NOM-003", f"{d_dev} − {d_ded} = {d_dev - d_ded}, pero ComprobanteTotal es {d_tot}."))
    sum_dev = _sum_money(one("Devengados"))
    sum_ded = _sum_money(one("Deducciones"))
    if abs(sum_dev - d_dev) > Decimal("1.00") or abs(sum_ded - d_ded) > Decimal("1.00"):
        out.append(_f("SBX-NOM-004", f"Suma de devengados {money(sum_dev)} vs total {d_dev}; "
                                     f"suma de deducciones {money(sum_ded)} vs total {d_ded}."))
    periodo = one("Periodo")
    if periodo is not None:
        ing, ini, fin = (periodo.get(k, "") for k in ("FechaIngreso", "FechaLiquidacionInicio", "FechaLiquidacionFin"))
        if not (ing and ini and fin and ing <= fin and ini <= fin):
            out.append(_f("SBX-NOM-005"))
    else:
        out.append(_f("SBX-NOM-005", "Falta el elemento Periodo."))
    worker = one("Trabajador")
    if worker is None or not all(worker.get(k) for k in ("TipoDocumento", "NumeroDocumento", "PrimerApellido", "PrimerNombre")) \
            or worker.get("TipoDocumento") not in {"11", "12", "13", "21", "22", "31", "41", "42", "47", "50", "91"}:
        out.append(_f("SBX-NOM-006"))
    basic = root.xpath("/*/*[local-name()='Devengados']/*[local-name()='Basico']")
    if not basic or money(basic[0].get("SueldoTrabajado", "0")) <= 0:
        out.append(_f("SBX-NOM-007"))
    if p.kind == "payroll":
        if not root.xpath("/*/*[local-name()='Deducciones']/*[local-name()='Salud']") or \
                not root.xpath("/*/*[local-name()='Deducciones']/*[local-name()='FondoPension']"):
            out.append(_f("SBX-NOM-008"))
    expected_type = {"payroll": "102", "payroll_adjustment": "103"}[p.kind]
    if p.type_code != expected_type:
        out.append(_f("SBX-NOM-009", f"TipoXML '{p.type_code}' no corresponde a este documento (esperado {expected_type})."))
    if p.kind == "payroll_adjustment" and not root.xpath("/*/*[local-name()='ReemplazandoPredecesor' or local-name()='EliminandoPredecesor']"):
        out.append(_f("SBX-NOM-009", "El ajuste no referencia al documento que reemplaza o elimina."))
    if p.issue_time and not p.issue_time.endswith("-05:00"):
        out.append(_f("SBX-NOM-010"))
    return out
