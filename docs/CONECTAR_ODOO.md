# Conectar Odoo 19 al simulador

Probado con Odoo 19 Community, `l10n_co_electronic_invoice` y `l10n_co_electronic_invoice_self` (OCA l10n-colombia).

> Usa **una base de pruebas**: el aprovisionamiento cambia compañía, diario, impuestos y certificados.

## 1. Arranca el simulador
```bash
python -m sandbox.app          # http://127.0.0.1:8099
```

## 2. Apunta Odoo al simulador
El módulo OCA trae la URL de habilitación de la DIAN fija. El addon `odoo_connector/l10n_co_dian_sandbox_connector` la reemplaza **solo si**
defines la variable de entorno o la opción:

```bash
export DIAN_SANDBOX_URL=http://127.0.0.1:8099/WcfDianCustomerServices.svc     # o en odoo.conf [options]: dian_sandbox_url = ...
```
Agrega `odoo_connector/` a `addons_path`, actualiza la lista de aplicaciones e instala **Conector al simulador DIAN**. En el log de Odoo verás
`*** DIAN SANDBOX *** El modo Habilitación apunta a ...`. Sin la variable el addon no cambia nada.

## 3. Aprovisiona la base
```bash
python tools/provision_odoo.py --sandbox http://127.0.0.1:8099 --odoo http://localhost:8069 --db MI_BASE --user admin --password admin
```
Hace: compañía en Colombia con el NIT ficticio del simulador, diario de ventas en **Habilitación** (Software ID, PIN, TestSetId, prefijo `SETP`,
rango y clave técnica), sube el certificado `.p12` de prueba, asigna el tipo de impuesto DIAN, y crea un cliente y un producto de prueba.
Usa `--dry-run` para ver los cambios sin aplicarlos.

## 4. Envía el set de pruebas
```bash
python tools/odoo_flow.py --sandbox http://127.0.0.1:8099 --odoo http://localhost:8069 --db MI_BASE
```
Crea y envía 1 factura, 2 notas crédito y 2 notas débito (cantidades configurables) y consulta el estado de cada una. En el simulador,
**Resumen** pasa a «COMPLETO» y **Preparación** muestra lo cumplido. A mano en Odoo: confirma la factura, pulsa enviar/procesar y luego
«Consultar estado DIAN»; las notas solo se pueden emitir cuando la factura ya fue aceptada.

## Notas sobre la localización
- En habilitación el envío es asíncrono: Odoo marca «Enviado» y el resultado llega al consultar el estado (`GetStatusZip`).
- Las notas necesitan el **Concepto de corrección** (NC o ND), una factura aceptada como referencia, y el tipo de documento 91 (NC) o 92 (ND).
- Cada impuesto necesita su **tipo de impuesto DIAN**; cada producto, UNSPSC y unidad UNECE; cada cliente, régimen y responsabilidades.

## Otros softwares contables
Cualquier software que hable SOAP con la DIAN sirve: usa la URL, el WSDL (`?wsdl`) y los datos de la pestaña **Conectar**. La verificación de
firma usa el certificado que viaja dentro del XML, así que también acepta el que genera el simulador o cualquier otro autofirmado de pruebas.
