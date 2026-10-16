# Cobertura del simulador

Resumen honesto de qué se simula, qué se verifica de verdad y qué no. Léelo antes de confiar en un resultado.

## Servicios SOAP
| Operación | Estado |
|---|---|
| SendTestSetAsync, GetStatusZip, GetStatus | ✔ |
| SendBillSync, SendBillAsync, SendNominaSync | ✔ (envío directo, sin set de pruebas) |
| SendEventUpdateStatus (eventos RADIAN) | ✔ validación básica |
| GetNumberingRange | ✔ (rangos configurables) |
| Autenticación WS-Security | ✘ se ignora el encabezado de seguridad |
| Resto de operaciones de la DIAN | ✘ responden con un SOAP Fault |

## Documentos
| Documento | Lectura | CUFE/CUDE/CUNE | Reglas propias |
|---|---|---|---|
| Factura electrónica de venta | ✔ | CUFE (clave técnica) | ✔ |
| Nota crédito / nota débito | ✔ | CUDE (PIN) | ✔ + documento referenciado |
| Documento soporte y su ajuste | ✔ | CUDE (PIN) | ✔ (parcial) |
| Nómina electrónica individual | ✔ | CUNE | ✔ (totales, trabajador, deducciones, TipoXML) |
| Nómina electrónica de ajuste | ✔ lectura | CUNE | ✔ (parcial, sin muestra de prueba) |
| Eventos RADIAN | ✔ | — | ✔ código y factura referenciada |
| Contingencia, exportación completa, documento equivalente, mandato (cuenta de terceros) | ✘ | | |

## Qué se verifica criptográficamente
- Firma XML (xmldsig/XAdES-EPES): resumen de cada referencia y `SignatureValue` con el certificado incluido. Cualquier cambio posterior a la firma se detecta.
- CUFE/CUDE/CUNE: SHA-384 de la cadena del anexo técnico, comparada con la del documento (fórmulas validadas contra la salida real de Odoo + OCA).
- SoftwareSecurityCode = SHA-384(SoftwareID + PIN + número).

## Lo que NO hace
- No valida que el certificado sea de una entidad certificadora autorizada (solo su vigencia y que la firma coincida).
- No consulta RUT, responsables de IVA, numeración real ni listas de la DIAN; no valida códigos de municipio, CIIU, UNSPSC ni tablas completas de la DIAN.
- No genera el `ApplicationResponse` firmado de la DIAN: devuelve uno mínimo marcado como simulado.
- No reproduce las reglas oficiales (códigos de rechazo `ZB…`, `FA…`, `NE…`): usa las propias `SBX-…`.
- Los parámetros (UVT, antigüedad máxima, cantidades del set) son configurables y deben mantenerse al día.

## Cómo comprobar la cobertura
`pytest` ejecuta una prueba por cada regla del catálogo; si añades una regla sin prueba, la suite falla.
