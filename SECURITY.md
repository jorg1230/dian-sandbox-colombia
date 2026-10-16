# Seguridad

Este proyecto es un **simulador de desarrollo**. No está pensado para exponerse a Internet ni para manejar datos reales.

- No cargues **certificados ni claves privadas reales** (`.p12`, `.pfx`, `.key`): el simulador genera su propio certificado de prueba.
- No uses NIT, documentos de identidad ni datos personales de terceros; las muestras del repositorio son ficticias.
- La interfaz no tiene autenticación. Por defecto escucha solo en `127.0.0.1`. Si cambias `SANDBOX_HOST`, protégelo con una red privada o un proxy con autenticación.
- Las credenciales de prueba son aleatorias y se guardan en texto plano en `data/sandbox.db` (ignorado por git).
- El simulador no valida la cadena de confianza de los certificados: que un documento «pase» aquí no significa que su firma sea válida ante la DIAN.

**Reportar un problema de seguridad:** abre un *issue* privado (Security advisories de GitHub) sin incluir datos reales.
