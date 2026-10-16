"""Conector al simulador DIAN. SOLO PARA DESARROLLO Y PRUEBAS."""
import configparser
import logging
import os

_logger = logging.getLogger(__name__)


def _sandbox_url():
    url = os.environ.get("DIAN_SANDBOX_URL", "").strip()
    if url:
        return url
    try:
        from odoo.tools import config

        rcfile = config.rcfile
        if rcfile and os.path.exists(rcfile):
            parser = configparser.ConfigParser()
            parser.read(rcfile, encoding="utf-8")
            return parser.get("options", "dian_sandbox_url", fallback="").strip()
    except Exception:  # pragma: no cover - nunca debe impedir el arranque de Odoo
        _logger.exception("No se pudo leer odoo.conf para dian_sandbox_url")
    return ""


def post_load():
    """Se ejecuta al cargar el módulo (antes de abrir bases de datos)."""
    url = _sandbox_url()
    if not url:
        _logger.info("l10n_co_dian_sandbox_connector instalado, pero sin DIAN_SANDBOX_URL: no se cambia nada.")
        return
    from odoo.addons.l10n_co_electronic_invoice_self.utils import constants

    constants.DIAN_URLS["test"] = url
    _logger.warning(
        "*** DIAN SANDBOX *** El modo Habilitación apunta a %s (simulador, solo desarrollo; "
        "los documentos NO llegan a la DIAN).", url)
