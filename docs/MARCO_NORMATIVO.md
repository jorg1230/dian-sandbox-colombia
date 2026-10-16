# Marco normativo de referencia

> **Orientativo. No es asesoría legal ni tributaria.** Las normas se citan por nombre y número tal como se conocen y pueden haber sido
> modificadas o derogadas: confirma siempre el texto vigente en el normograma y en el micrositio de facturación electrónica de la DIAN
> (<https://micrositios.dian.gov.co/sistema-de-facturacion-electronica/>). El simulador no se actualiza solo con la normativa.

## Normas que conviene tener presentes al conectar un software contable

| Norma | De qué trata | Cómo lo toca este proyecto |
|---|---|---|
| Estatuto Tributario, arts. 615, 616-1, 617 y 618 | Obligación de expedir factura y requisitos (identificación del vendedor y del adquirente, fecha, descripción, valores, discriminación del IVA) | Reglas de partes, totales, impuestos, ítems y fechas (`SBX-PAR`, `SBX-TOT`, `SBX-IMP`, `SBX-ITM`) |
| Estatuto Tributario, art. 771-2 | La factura (o el documento soporte) como soporte de costos, deducciones e impuestos descontables | Documento soporte en adquisiciones a no obligados a facturar |
| Decreto 358 de 2020 | Reglamenta la facturación electrónica y los documentos que la acompañan | Estructura general de documentos y notas |
| Resolución 000042 de 2020 y Resolución 000165 de 2023 | Desarrollo del sistema de facturación electrónica y su Anexo Técnico (formato UBL 2.1, CUFE/CUDE, firma, validaciones) | Formato UBL 2.1, CUFE/CUDE con SHA-384, firma XAdES, rangos de numeración |
| Resolución 000013 de 2021 | Documento soporte de pago de nómina electrónica | Nómina electrónica: CUNE, totales, trabajador, deducciones |
| Resolución 000167 de 2021 | Documento soporte en adquisiciones a sujetos no obligados a facturar | Documento soporte y su nota de ajuste |
| Resolución 000015 de 2021 | RADIAN: registro de facturas electrónicas como título valor y eventos | Eventos RADIAN (acuse, recibo, aceptación, reclamo) |
| Leyes 1231 de 2008 y 1676 de 2013 | La factura como título valor y su circulación (factoring) | Contexto de RADIAN |
| Ley 527 de 1999 y Decreto 2364 de 2012 | Mensajes de datos y firma electrónica/digital | Firma digital del XML con certificado de una entidad autorizada |
| Ley 1581 de 2012 y Decreto 1377 de 2013 | Protección de datos personales (habeas data) | Las facturas y la nómina contienen datos personales: no cargues datos reales en el simulador |

## Cómo es el proceso real de habilitación (resumen de la DIAN)

1. Registro en el portal de **Habilitación** de la DIAN y elección del modo de operación (software propio, proveedor tecnológico o facturación gratuita DIAN).
2. La DIAN entrega los datos de pruebas: **Software ID, PIN y TestSetId**, la URL del servicio y rangos de numeración de prueba.
3. Se envía el **set de pruebas** firmado con un certificado de una entidad certificadora autorizada. Las cantidades dependen del modo de operación;
   al consultar el micrositio de la DIAN, para *software propio* se piden notas crédito y débito aceptadas además de facturas, para *proveedor tecnológico* 6 facturas
   y para la *facturación gratuita* 2 facturas, 1 nota débito y 1 nota crédito. **Verifica las cantidades en tu portal**: el simulador las deja configurables.
4. Con el set aprobado se solicita la numeración de facturación en MUISCA y se pasa a producción.

> Los valores de ejemplo que la DIAN publica en su micrositio (por ejemplo el Software ID y PIN del facturador gratuito) son públicos y de ejemplo:
> no tienen carácter secreto, pero tampoco los uses en producción.

## Facturación a nombre propio y por cuenta de terceros

- **Persona natural emisora** (facturar «a su nombre»): el simulador comprueba que el emisor informe sus responsabilidades fiscales y que su identificación
  y dígito de verificación sean coherentes. La clasificación (responsable o no de IVA, régimen simple, etc.) la determina el RUT, que el simulador no consulta.
- **Facturación por cuenta de terceros (mandato)** y **contingencia**: **no están implementadas**. Si las necesitas, consulta a tu contador y abre un issue.

## Lo que este proyecto no reemplaza
La validación real de la DIAN, la asesoría de un contador o abogado tributarista, ni la verificación de los parámetros que cambian cada año (UVT, tarifas, resoluciones).
