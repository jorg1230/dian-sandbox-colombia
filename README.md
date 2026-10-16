# DIAN Sandbox Colombia

> ⚠️ **Simulador SOLO para desarrollo y pruebas.** No es la DIAN, no usa sus sistemas y **no tiene validez legal ni tributaria**.
> Las reglas son un subconjunto propio (códigos `SBX-`), inspirado en los requisitos públicos, **no las reglas oficiales**. Sirve para
> ensayar la integración de un software contable antes de enfrentar el filtro real; la habilitación con la DIAN se hace siempre en su portal.

Servidor que imita el servicio web de **habilitación** de la facturación electrónica de la DIAN (WCF/SOAP) y trae una interfaz gráfica.
Genera sus propias credenciales de prueba (NIT, Software ID, PIN, TestSetId, clave técnica, rango de numeración y un certificado `.p12`),
así que se conecta en minutos, por ejemplo con **Odoo**.

*English summary: a local mock of Colombia's DIAN e-invoicing SOAP service (test/habilitación environment) with a web UI, generated test credentials and
test certificate, XAdES signature + CUFE/CUDE/CUNE verification, and a rule pack for invoices, credit/debit notes, support documents, electronic payroll and RADIAN events. Dev/testing only, not official.*

## Qué hace

| Servicio SOAP | Qué simula |
|---|---|
| `SendTestSetAsync` | Recibe un zip con el XML, lo valida y devuelve un `ZipKey`; el resultado se consulta después |
| `GetStatusZip` / `GetStatus` | Devuelve `StatusCode` `00` (aceptado) o `99` (rechazado) con la lista de errores |
| `SendBillSync` / `SendBillAsync` / `SendNominaSync` | Envío directo, para documentos sueltos |
| `SendEventUpdateStatus` | Eventos RADIAN (acuse, reclamo, recibo, aceptación…) |
| `GetNumberingRange` | Devuelve los rangos de numeración con su clave técnica |
| `?wsdl` | WSDL simplificado para generar clientes |

**Documentos:** factura electrónica, nota crédito, nota débito, documento soporte, nómina electrónica (individual y de ajuste) y eventos RADIAN.

**Validaciones reales** (no son un «siempre aceptado»): XML bien formado y tipo de documento, **firma XAdES verificada criptográficamente**
(resúmenes y `SignatureValue`, certificado y vigencia), **CUFE / CUDE / CUNE recalculados con SHA-384**, NIT y dígito de verificación, SoftwareID y
código de seguridad, rango de numeración y vigencia, totales, notas con concepto de corrección y documento referenciado, duplicados, y un paquete
de reglas «filtro DIAN» (partes, impuestos, formas de pago, fechas, QR, moneda, ítems, nómina). Cada regla tiene su prueba automática.

**Interfaz:** resumen del set de pruebas (cuántas facturas y notas van aceptadas), *Conectar* (credenciales y certificado para copiar), *Preparación*
(lista de lo que tu software ya demostró), documentos con sus hallazgos y XML, subida manual de XML y configuración.

## Inicio rápido

```bash
python -m venv .venv && . .venv/bin/activate          # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m sandbox.app                                  # http://127.0.0.1:8099
```

Con Docker: `docker compose up --build` (puerto 8099).

1. Abre <http://127.0.0.1:8099/connect>: ahí están la URL SOAP, el NIT, Software ID, PIN, TestSetId, clave técnica, la resolución de prueba y el **certificado `.p12`** (contraseña incluida).
2. Configura tu software con esos datos y envía documentos. Mira el resultado en **Documentos** y el avance en **Resumen** / **Preparación**.
3. Sin software a mano: <http://127.0.0.1:8099/upload> valida un XML o zip, o usa `python tools/send_samples.py --align` para enviar los de `samples/` (ajusta el simulador a los datos con que se firmaron).

Las credenciales son aleatorias en cada instalación y se guardan en `data/sandbox.db`. Se cambian en **Configuración**.

## Conectar Odoo 19 (localización OCA)

Funciona con los módulos OCA `l10n_co_electronic_invoice` y `l10n_co_electronic_invoice_self`. Pasos completos en [docs/CONECTAR_ODOO.md](docs/CONECTAR_ODOO.md):

```bash
# 1) con Odoo detenido, instala el addon conector (carpeta odoo_connector/) y arráncalo con la URL del simulador
export DIAN_SANDBOX_URL=http://127.0.0.1:8099/WcfDianCustomerServices.svc
# 2) configura compañía, diario, certificado, impuestos, cliente y producto de prueba en una base de PRUEBAS
python tools/provision_odoo.py --sandbox http://127.0.0.1:8099 --odoo http://localhost:8069 --db MI_BASE_DE_PRUEBAS
# 3) genera una factura, notas crédito y débito y envíalas
python tools/odoo_flow.py --sandbox http://127.0.0.1:8099 --odoo http://localhost:8069 --db MI_BASE_DE_PRUEBAS
```

## Pruebas

```bash
pip install -r requirements-dev.txt
pytest
```

Los documentos de `samples/` se generaron con Odoo 19 y los módulos OCA citados, usando datos **ficticios** (NIT 900000001, «Empresa Demo SAS»…).
Las pruebas toman un documento válido y lo alteran para comprobar que cada regla se dispara.

## Límites (léelos)

- **No es la DIAN.** Aceptar aquí no garantiza que la DIAN acepte; las reglas oficiales cambian y esto no se mantiene al día con ellas.
- El simulador **no valida la cadena de confianza** del certificado (que lo emita una entidad certificadora autorizada) ni consulta RUT, listas de responsables ni numeración real.
- No cubre contingencia, facturación por cuenta de terceros (mandato), exportación completa, documento equivalente electrónico ni el resto de eventos RADIAN (endoso, mandato, limitación…).
- El valor de la UVT y otros parámetros de las reglas son configurables y **hay que actualizarlos**.
- Detalle en [docs/COBERTURA.md](docs/COBERTURA.md) y marco legal de referencia en [docs/MARCO_NORMATIVO.md](docs/MARCO_NORMATIVO.md).

## Seguridad y datos

Úsalo solo con datos ficticios o de pruebas. **No cargues certificados ni claves reales**, ni NIT de terceros. Ver [SECURITY.md](SECURITY.md).

## Licencia

MIT (ver `LICENSE`). El addon de `odoo_connector/` declara `LGPL-3` en su manifiesto por la convención de Odoo. Los XML de `samples/` son salida de
módulos OCA (AGPL-3) con datos ficticios.
