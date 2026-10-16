{
    "name": "Colombia - Conector al simulador DIAN (SOLO DESARROLLO)",
    "version": "19.0.1.0.0",
    "category": "Accounting/Localizations",
    "summary": "Apunta la facturación electrónica de habilitación al simulador local de la DIAN. Solo desarrollo.",
    "description": """
Redirige las llamadas SOAP del modo "Habilitación" de l10n_co_electronic_invoice_self hacia el simulador
dian-sandbox-colombia, definido en la variable de entorno DIAN_SANDBOX_URL o en la opción dian_sandbox_url de odoo.conf.
NO instalar en producción: sin esa variable el módulo no cambia nada.
""",
    "author": "dian-sandbox-colombia",
    "license": "LGPL-3",
    "depends": ["l10n_co_electronic_invoice_self"],
    "post_load": "post_load",
    "installable": True,
}
