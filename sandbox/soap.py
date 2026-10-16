"""Servicio SOAP que imita al WCF de la DIAN (habilitación): SendTestSetAsync, SendBillSync,
GetStatusZip, GetStatus, GetNumberingRange y SendEventUpdateStatus."""
from __future__ import annotations

import base64
import io
import uuid
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from lxml import etree

from . import TAG
from .processor import Processor

WCF_NS = "http://wcf.dian.colombia"
SOAP_NS = "http://www.w3.org/2003/05/soap-envelope"


def _now_z() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def envelope(body_xml: str) -> bytes:
    """Sobre SOAP con los prefijos que usa la DIAN (s, o, u, b, c) para que los clientes lo lean igual."""
    return (
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:a="http://www.w3.org/2005/08/addressing" '
        'xmlns:o="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" '
        'xmlns:u="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">'
        '<s:Header><o:Security><u:Timestamp><u:Created>%s</u:Created></u:Timestamp></o:Security></s:Header>'
        "<s:Body>%s</s:Body></s:Envelope>" % (_now_z(), body_xml)
    ).encode("utf-8")


def fault(reason: str, code: str = "s:Sender") -> bytes:
    return envelope(
        f'<s:Fault><s:Code><s:Value>{code}</s:Value></s:Code>'
        f'<s:Reason><s:Text xml:lang="es">{escape(TAG + " " + reason)}</s:Text></s:Reason></s:Fault>')


def _errors_xml(messages: list[str]) -> str:
    if not messages:
        return "<b:ErrorMessage/>"
    return "<b:ErrorMessage>" + "".join(f"<c:string>{escape(m)}</c:string>" for m in messages) + "</b:ErrorMessage>"


def dian_response_xml(doc: dict, wrapper: str = "b:DianResponse") -> str:
    """Bloque DianResponse/Result de un documento procesado."""
    valid = bool(doc["is_valid"])
    errors = [f"{f['code']}: {f['message']}" for f in doc["findings"] if f["severity"] == "error"]
    warns = [f"{f['code']}: {f['message']}" for f in doc["findings"] if f["severity"] == "warning"]
    desc = "Procesado Correctamente." if valid else "Validación contiene errores en campos mandatorios."
    msg = f"{TAG} {'Documento aceptado por el simulador.' if valid else 'Documento rechazado por el simulador.'}"
    app = _application_response(doc)
    return (
        f"<{wrapper}>"
        f"<b:ErrorMessage>{''.join(f'<c:string>{escape(m)}</c:string>' for m in errors + warns)}</b:ErrorMessage>"
        f"<b:IsValid>{'true' if valid else 'false'}</b:IsValid>"
        f"<b:StatusCode>{'00' if valid else '99'}</b:StatusCode>"
        f"<b:StatusDescription>{escape(desc)}</b:StatusDescription>"
        f"<b:StatusMessage>{escape(msg)}</b:StatusMessage>"
        f"<b:XmlBase64Bytes>{base64.b64encode(app).decode()}</b:XmlBase64Bytes>"
        f"<b:XmlBytes i:nil=\"true\" xmlns:i=\"http://www.w3.org/2001/XMLSchema-instance\"/>"
        f"<b:XmlDocumentKey>{escape(doc.get('uuid') or '')}</b:XmlDocumentKey>"
        f"<b:XmlFileName>{escape(doc.get('file_name') or '')}</b:XmlFileName>"
        f"</{wrapper}>"
    )


def _application_response(doc: dict) -> bytes:
    """ApplicationResponse mínimo (no firmado por la DIAN; el simulador no tiene su certificado)."""
    code = "02" if doc["is_valid"] else "04"
    text = "Documento validado por la DIAN" if doc["is_valid"] else "Documento rechazado por la DIAN"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ApplicationResponse xmlns="urn:oasis:names:specification:ubl:schema:xsd:ApplicationResponse-2" '
        'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
        'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
        f"<cbc:Note>{TAG} Respuesta simulada; no tiene validez ante la DIAN.</cbc:Note>"
        f"<cbc:ID>{doc['id']}</cbc:ID><cbc:UUID>{escape(doc.get('uuid') or '')}</cbc:UUID>"
        f"<cbc:IssueDate>{datetime.now(timezone.utc).date()}</cbc:IssueDate>"
        f"<cac:DocumentResponse><cac:Response><cbc:ResponseCode>{code}</cbc:ResponseCode>"
        f"<cbc:Description>{text}</cbc:Description></cac:Response></cac:DocumentResponse>"
        "</ApplicationResponse>").encode("utf-8")


def _first(root, name):
    r = root.xpath(f"//*[local-name()='{name}']")
    return r[0] if r else None


def _val(root, name) -> str:
    n = _first(root, name)
    return (n.text or "").strip() if n is not None else ""


def unzip_documents(content_b64: str) -> list[tuple[str, bytes]]:
    raw = base64.b64decode("".join(content_b64.split()))
    out = []
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".xml"):
                continue
            out.append((info.filename, zf.read(info)))
    return out


class DianService:
    def __init__(self, processor: Processor):
        self.p = processor
        self.store = processor.store

    # ------------------------------------------------------------------ entrada
    def handle(self, body: bytes, soap_action: str = "") -> tuple[bytes, int]:
        try:
            root = etree.fromstring(body, parser=etree.XMLParser(resolve_entities=False, no_network=True))
        except etree.XMLSyntaxError:
            return fault("El cuerpo de la solicitud no es un XML SOAP válido."), 400
        bodies = root.xpath("//*[local-name()='Body']/*")
        if not bodies:
            return fault("La solicitud SOAP no tiene cuerpo."), 400
        op = etree.QName(bodies[0]).localname
        handler = {
            "SendTestSetAsync": self.send_test_set_async,
            "SendBillSync": self.send_bill_sync,
            "SendBillAsync": self.send_bill_async,
            "GetStatusZip": self.get_status_zip,
            "GetStatus": self.get_status,
            "GetNumberingRange": self.get_numbering_range,
            "SendEventUpdateStatus": self.send_event,
            "SendNominaSync": self.send_bill_sync,
        }.get(op)
        if not handler:
            return fault(f"Operación no soportada por el simulador: {op}"), 400
        self.store.log_op(op)
        try:
            return handler(bodies[0]), 200
        except (ValueError, zipfile.BadZipFile) as exc:
            return fault(f"Contenido inválido: {exc}"), 400

    # ---------------------------------------------------------------- operaciones
    def send_test_set_async(self, node) -> bytes:
        file_name, content, test_set = _val(node, "fileName"), _val(node, "contentFile"), _val(node, "testSetId")
        expected = self.store.settings().get("test_set_id", "")
        if not content:
            raise ValueError("falta contentFile")
        if expected and test_set != expected:
            return envelope(
                '<SendTestSetAsyncResponse xmlns="http://wcf.dian.colombia">'
                '<SendTestSetAsyncResult xmlns:b="http://schemas.datacontract.org/2004/07/UploadDocumentResponse" '
                'xmlns:c="http://schemas.microsoft.com/2003/10/Serialization/Arrays">'
                + _errors_xml([f"{TAG} El TestSetId enviado no corresponde al registrado para este software."])
                + "<b:ZipKey/></SendTestSetAsyncResult></SendTestSetAsyncResponse>")
        zip_key = str(uuid.uuid4())
        for name, xml in unzip_documents(content):
            self.p.process(xml, file_name=name or file_name, zip_key=zip_key, test_set_id=test_set, via="SendTestSetAsync")
        return envelope(
            '<SendTestSetAsyncResponse xmlns="http://wcf.dian.colombia">'
            '<SendTestSetAsyncResult xmlns:b="http://schemas.datacontract.org/2004/07/UploadDocumentResponse" '
            'xmlns:c="http://schemas.microsoft.com/2003/10/Serialization/Arrays">'
            f"<b:ErrorMessageList/><b:ZipKey>{zip_key}</b:ZipKey></SendTestSetAsyncResult>"
            "</SendTestSetAsyncResponse>")

    def send_bill_async(self, node) -> bytes:
        content = _val(node, "contentFile")
        zip_key = str(uuid.uuid4())
        for name, xml in unzip_documents(content):
            self.p.process(xml, file_name=name, zip_key=zip_key, test_set_id="", via="SendBillAsync")
        return envelope(
            '<SendBillAsyncResponse xmlns="http://wcf.dian.colombia">'
            '<SendBillAsyncResult xmlns:b="http://schemas.datacontract.org/2004/07/UploadDocumentResponse" '
            'xmlns:c="http://schemas.microsoft.com/2003/10/Serialization/Arrays">'
            f"<b:ErrorMessageList/><b:ZipKey>{zip_key}</b:ZipKey></SendBillAsyncResult></SendBillAsyncResponse>")

    def send_bill_sync(self, node) -> bytes:
        content = _val(node, "contentFile")
        op = etree.QName(node).localname
        docs = unzip_documents(content)
        if not docs:
            raise ValueError("el zip no contiene ningún XML")
        doc = self.p.process(docs[0][1], file_name=docs[0][0], zip_key="", test_set_id="", via=op)
        return envelope(
            f'<{op}Response xmlns="http://wcf.dian.colombia">'
            f'<{op}Result xmlns:b="http://schemas.datacontract.org/2004/07/UploadDocumentResponse" '
            'xmlns:c="http://schemas.microsoft.com/2003/10/Serialization/Arrays" '
            f'xmlns:i="http://www.w3.org/2001/XMLSchema-instance">'
            + dian_response_xml(doc, wrapper="b:Content").replace("<b:Content>", "").replace("</b:Content>", "")
            + f"</{op}Result></{op}Response>")

    def get_status_zip(self, node) -> bytes:
        track = _val(node, "trackId")
        docs = self.store.by_zip_key(track)
        inner = "".join(dian_response_xml(d) for d in docs) if docs else (
            "<b:DianResponse><b:IsValid>false</b:IsValid><b:StatusCode>90</b:StatusCode>"
            f"<b:StatusDescription>TrackId no encontrado.</b:StatusDescription>"
            f"<b:StatusMessage>{escape(TAG)} No existe un envío con ese ZipKey.</b:StatusMessage></b:DianResponse>")
        return envelope(
            '<GetStatusZipResponse xmlns="http://wcf.dian.colombia">'
            '<GetStatusZipResult xmlns:b="http://schemas.datacontract.org/2004/07/DianResponse" '
            'xmlns:c="http://schemas.microsoft.com/2003/10/Serialization/Arrays" '
            f'xmlns:i="http://www.w3.org/2001/XMLSchema-instance">{inner}</GetStatusZipResult></GetStatusZipResponse>')

    def get_status(self, node) -> bytes:
        track = _val(node, "trackId")
        d = self.store.by_track_id(track)
        if d:
            inner = dian_response_xml(d, wrapper="b:Content").replace("<b:Content>", "").replace("</b:Content>", "")
        else:
            inner = ("<b:IsValid>false</b:IsValid><b:StatusCode>90</b:StatusCode>"
                     "<b:StatusDescription>TrackId no encontrado.</b:StatusDescription>"
                     f"<b:StatusMessage>{escape(TAG)} No existe un documento con ese identificador.</b:StatusMessage>")
        return envelope(
            '<GetStatusResponse xmlns="http://wcf.dian.colombia">'
            '<GetStatusResult xmlns:b="http://schemas.datacontract.org/2004/07/DianResponse" '
            'xmlns:c="http://schemas.microsoft.com/2003/10/Serialization/Arrays" '
            f'xmlns:i="http://www.w3.org/2001/XMLSchema-instance">{inner}</GetStatusResult></GetStatusResponse>')

    def get_numbering_range(self, node) -> bytes:
        items = ""
        for r in self.store.ranges():
            key = r.get("technical_key") or self.store.settings().get("technical_key", "")
            items += (
                "<c:NumberRangeResponse>"
                f"<c:ResolutionNumber>{escape(str(r['resolution']))}</c:ResolutionNumber>"
                f"<c:ResolutionDate>{escape(str(r['valid_from']))}</c:ResolutionDate>"
                f"<c:Prefix>{escape(str(r['prefix']))}</c:Prefix>"
                f"<c:FromNumber>{r['from_number']}</c:FromNumber><c:ToNumber>{r['to_number']}</c:ToNumber>"
                f"<c:ValidDateFrom>{escape(str(r['valid_from']))}</c:ValidDateFrom>"
                f"<c:ValidDateTo>{escape(str(r['valid_to']))}</c:ValidDateTo>"
                f"<c:TechnicalKey>{escape(key)}</c:TechnicalKey></c:NumberRangeResponse>")
        return envelope(
            '<GetNumberingRangeResponse xmlns="http://wcf.dian.colombia">'
            '<GetNumberingRangeResult xmlns:b="http://schemas.datacontract.org/2004/07/NumberRangeResponse" '
            'xmlns:c="http://schemas.datacontract.org/2004/07/NumberRangeResponse">'
            "<b:OperationCode>100</b:OperationCode>"
            f"<b:OperationDescription>{escape(TAG)} Consulta simulada</b:OperationDescription>"
            f"<b:ResponseList>{items}</b:ResponseList></GetNumberingRangeResult></GetNumberingRangeResponse>")

    def send_event(self, node) -> bytes:
        content = _val(node, "contentFile")
        docs = unzip_documents(content)
        if not docs:
            raise ValueError("el zip no contiene ningún XML")
        doc = self.p.process(docs[0][1], file_name=docs[0][0], zip_key="", test_set_id="", via="SendEventUpdateStatus")
        return envelope(
            '<SendEventUpdateStatusResponse xmlns="http://wcf.dian.colombia">'
            '<SendEventUpdateStatusResult xmlns:b="http://schemas.datacontract.org/2004/07/UploadDocumentResponse" '
            'xmlns:c="http://schemas.microsoft.com/2003/10/Serialization/Arrays" '
            'xmlns:i="http://www.w3.org/2001/XMLSchema-instance">'
            + dian_response_xml(doc, wrapper="b:Content").replace("<b:Content>", "").replace("</b:Content>", "")
            + "</SendEventUpdateStatusResult></SendEventUpdateStatusResponse>")


WSDL = """<?xml version="1.0" encoding="utf-8"?>
<!-- {tag} WSDL simplificado del simulador. No es el WSDL oficial de la DIAN. -->
<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" xmlns:soap12="http://schemas.xmlsoap.org/wsdl/soap12/"
    xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:tns="{ns}" targetNamespace="{ns}"
    name="WcfDianCustomerServices">
  <wsdl:types><xs:schema elementFormDefault="qualified" targetNamespace="{ns}">
{elements}
  </xs:schema></wsdl:types>
{messages}
  <wsdl:portType name="IWcfDianCustomerServices">
{port_ops}
  </wsdl:portType>
  <wsdl:binding name="WcfDianCustomerServices" type="tns:IWcfDianCustomerServices">
    <soap12:binding transport="http://schemas.xmlsoap.org/soap/http"/>
{bind_ops}
  </wsdl:binding>
  <wsdl:service name="WcfDianCustomerServices">
    <wsdl:port name="WcfDianCustomerServices" binding="tns:WcfDianCustomerServices">
      <soap12:address location="{location}"/>
    </wsdl:port>
  </wsdl:service>
</wsdl:definitions>
"""

OPERATIONS = {
    "SendTestSetAsync": ["fileName", "contentFile", "testSetId"],
    "SendBillSync": ["fileName", "contentFile"],
    "SendBillAsync": ["fileName", "contentFile"],
    "SendEventUpdateStatus": ["contentFile"],
    "GetStatusZip": ["trackId"],
    "GetStatus": ["trackId"],
    "GetNumberingRange": ["accountCode", "accountCodeT", "softwareCode"],
}


def build_wsdl(location: str) -> str:
    elements, messages, port_ops, bind_ops = [], [], [], []
    for op, fields in OPERATIONS.items():
        inner = "".join(f'<xs:element minOccurs="0" name="{f}" type="xs:string"/>' for f in fields)
        elements.append(f'    <xs:element name="{op}"><xs:complexType><xs:sequence>{inner}</xs:sequence>'
                        f'</xs:complexType></xs:element>')
        elements.append(f'    <xs:element name="{op}Response"><xs:complexType><xs:sequence>'
                        f'<xs:any minOccurs="0" processContents="lax"/></xs:sequence></xs:complexType></xs:element>')
        messages.append(f'  <wsdl:message name="IWcf_{op}_InputMessage"><wsdl:part name="parameters" '
                        f'element="tns:{op}"/></wsdl:message>')
        messages.append(f'  <wsdl:message name="IWcf_{op}_OutputMessage"><wsdl:part name="parameters" '
                        f'element="tns:{op}Response"/></wsdl:message>')
        port_ops.append(f'    <wsdl:operation name="{op}"><wsdl:input wsaw:Action="{WCF_NS}/IWcfDianCustomerServices/{op}" '
                        f'message="tns:IWcf_{op}_InputMessage" xmlns:wsaw="http://www.w3.org/2006/05/addressing/wsdl"/>'
                        f'<wsdl:output message="tns:IWcf_{op}_OutputMessage"/></wsdl:operation>')
        bind_ops.append(f'    <wsdl:operation name="{op}"><soap12:operation soapAction="{WCF_NS}/'
                        f'IWcfDianCustomerServices/{op}" style="document"/><wsdl:input><soap12:body use="literal"/>'
                        f'</wsdl:input><wsdl:output><soap12:body use="literal"/></wsdl:output></wsdl:operation>')
    return WSDL.format(tag=TAG, ns=WCF_NS, elements="\n".join(elements), messages="\n".join(messages),
                       port_ops="\n".join(port_ops), bind_ops="\n".join(bind_ops), location=location)
