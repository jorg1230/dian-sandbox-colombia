"""Persistencia en SQLite: configuración, rangos de numeración y documentos recibidos."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

DEFAULT_SETTINGS = {
    # Datos del software registrado (inventados; cámbialos por los de tu prueba)
    "software_id": "00000000-0000-4000-8000-000000000001",
    "software_pin": "12345",
    "test_set_id": "00000000-0000-4000-8000-0000000000aa",
    # Clave técnica del rango de numeración (se usa para el CUFE de facturas)
    "technical_key": "0000000000000000000000000000000000000001",
    # NIT del emisor registrado, sin dígito de verificación. Vacío = aceptar cualquiera.
    "issuer_nit": "",
    "issuer_name": "EMPRESA DE PRUEBAS SANDBOX SAS",
    "cert_password": "sandbox",
    # Requisitos del set de pruebas
    "need_invoices": "1",
    "need_credit_notes": "2",
    "need_debit_notes": "2",
    # Nómina electrónica: cuántas nóminas individuales aceptadas pide tu set (0 = no se exige)
    "need_payrolls": "0",
    # Estrictez
    "verify_signature": "1",
    "verify_cufe": "1",
    "verify_totals": "1",
    "allow_external_references": "0",
    "require_environment_2": "1",
    "dian_filter": "1",
    # UVT vigente (COP). Se usa para el tope de venta a consumidor final; ACTUALÍZALO cada año.
    "uvt_value": "49799",
    # Antigüedad máxima en días del documento (0 = sin límite)
    "max_age_days": "0",
}

DEFAULT_RANGES = [
    {
        "resolution": "000000000",
        "prefix": "SETP",
        "from_number": 990000000,
        "to_number": 995000000,
        "valid_from": "2019-01-19",
        "valid_to": "2030-01-19",
        "technical_key": "",  # vacío = usa technical_key de la configuración
    }
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS ops (id INTEGER PRIMARY KEY AUTOINCREMENT, op TEXT, at TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS ranges (
    id INTEGER PRIMARY KEY AUTOINCREMENT, resolution TEXT, prefix TEXT, from_number INTEGER,
    to_number INTEGER, valid_from TEXT, valid_to TEXT, technical_key TEXT
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id TEXT, zip_key TEXT, file_name TEXT, test_set_id TEXT, via TEXT,
    kind TEXT, number TEXT, uuid TEXT, issuer_nit TEXT, customer_id TEXT,
    payable TEXT, issue_date TEXT,
    status_code TEXT, is_valid INTEGER, findings TEXT, parsed TEXT,
    xml BLOB, received_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_documents_track ON documents(track_id);
CREATE INDEX IF NOT EXISTS idx_documents_zip ON documents(zip_key);
CREATE INDEX IF NOT EXISTS idx_documents_uuid ON documents(uuid);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        self._seed()

    @contextmanager
    def _cx(self):
        with self._lock:
            yield self._conn
            self._conn.commit()

    def _seed(self):
        from .creds import new_credentials  # import tardío para evitar ciclos

        generated = new_credentials() if os.environ.get("SANDBOX_FIXED_CREDENTIALS") != "1" else {}
        with self._cx() as cx:
            for k, v in DEFAULT_SETTINGS.items():
                cx.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, generated.get(k, v)))
            if not cx.execute("SELECT 1 FROM ranges LIMIT 1").fetchone():
                for r in DEFAULT_RANGES:
                    cx.execute(
                        "INSERT INTO ranges(resolution, prefix, from_number, to_number, valid_from, valid_to,"
                        " technical_key) VALUES (:resolution, :prefix, :from_number, :to_number, :valid_from,"
                        " :valid_to, :technical_key)", r)

    # ------------------------------------------------------------- configuración
    def settings(self) -> dict:
        with self._cx() as cx:
            return {r["key"]: r["value"] for r in cx.execute("SELECT key, value FROM settings")}

    def set_settings(self, values: dict):
        with self._cx() as cx:
            for k, v in values.items():
                if k in DEFAULT_SETTINGS:
                    cx.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (k, str(v)))

    def flag(self, key: str) -> bool:
        return self.settings().get(key, "0") in ("1", "true", "on", "True")

    def ranges(self) -> list[dict]:
        with self._cx() as cx:
            return [dict(r) for r in cx.execute("SELECT * FROM ranges ORDER BY id")]

    def replace_ranges(self, ranges: list[dict]):
        with self._cx() as cx:
            cx.execute("DELETE FROM ranges")
            for r in ranges:
                cx.execute(
                    "INSERT INTO ranges(resolution, prefix, from_number, to_number, valid_from, valid_to,"
                    " technical_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (r.get("resolution", ""), r.get("prefix", ""), int(r.get("from_number") or 0),
                     int(r.get("to_number") or 0), r.get("valid_from", ""), r.get("valid_to", ""),
                     r.get("technical_key", "")))

    # --------------------------------------------------------------- documentos
    def add_document(self, d: dict) -> int:
        with self._cx() as cx:
            cur = cx.execute(
                "INSERT INTO documents(track_id, zip_key, file_name, test_set_id, via, kind, number, uuid,"
                " issuer_nit, customer_id, payable, issue_date, status_code, is_valid, findings, parsed, xml,"
                " received_at) VALUES (:track_id, :zip_key, :file_name, :test_set_id, :via, :kind, :number,"
                " :uuid, :issuer_nit, :customer_id, :payable, :issue_date, :status_code, :is_valid, :findings,"
                " :parsed, :xml, :received_at)",
                {**d, "findings": json.dumps(d.get("findings", []), ensure_ascii=False),
                 "parsed": json.dumps(d.get("parsed", {}), ensure_ascii=False, default=str),
                 "received_at": d.get("received_at") or now_iso()})
            return cur.lastrowid

    def _row(self, r):
        if r is None:
            return None
        d = dict(r)
        d["findings"] = json.loads(d["findings"] or "[]")
        d["parsed"] = json.loads(d["parsed"] or "{}")
        return d

    def document(self, doc_id: int):
        with self._cx() as cx:
            return self._row(cx.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone())

    def documents(self, limit: int = 200, kind: str = "", status: str = "", q: str = "") -> list[dict]:
        sql, args = "SELECT * FROM documents WHERE 1=1", []
        if q:
            like = f"%{q.strip()}%"
            sql += " AND (number LIKE ? OR customer_id LIKE ? OR issuer_nit LIKE ? OR uuid LIKE ?)"
            args += [like, like, like, like]
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        if status == "valid":
            sql += " AND is_valid = 1"
        elif status == "rejected":
            sql += " AND is_valid = 0"
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._cx() as cx:
            return [self._row(r) for r in cx.execute(sql, args)]

    def by_zip_key(self, zip_key: str) -> list[dict]:
        with self._cx() as cx:
            return [self._row(r) for r in cx.execute(
                "SELECT * FROM documents WHERE zip_key = ? ORDER BY id", (zip_key,))]

    def by_track_id(self, track_id: str):
        with self._cx() as cx:
            return self._row(cx.execute(
                "SELECT * FROM documents WHERE track_id = ? OR uuid = ? ORDER BY id DESC LIMIT 1",
                (track_id, track_id)).fetchone())

    def accepted_by_number(self, number: str, issuer_nit: str = "") -> dict | None:
        with self._cx() as cx:
            return self._row(cx.execute(
                "SELECT * FROM documents WHERE number = ? AND is_valid = 1 ORDER BY id DESC LIMIT 1",
                (number,)).fetchone())

    def accepted_by_uuid(self, uuid: str) -> dict | None:
        with self._cx() as cx:
            return self._row(cx.execute(
                "SELECT * FROM documents WHERE uuid = ? AND is_valid = 1 ORDER BY id DESC LIMIT 1",
                (uuid,)).fetchone())

    def counts(self, test_set_id: str | None = None) -> dict:
        sql = "SELECT kind, COUNT(*) AS n FROM documents WHERE is_valid = 1"
        args: list = []
        if test_set_id:
            sql += " AND test_set_id = ?"
            args.append(test_set_id)
        sql += " GROUP BY kind"
        with self._cx() as cx:
            return {r["kind"]: r["n"] for r in cx.execute(sql, args)}

    def totals(self) -> dict:
        with self._cx() as cx:
            row = cx.execute(
                "SELECT COUNT(*) AS total, SUM(is_valid) AS valid FROM documents").fetchone()
            return {"total": row["total"] or 0, "valid": row["valid"] or 0,
                    "rejected": (row["total"] or 0) - (row["valid"] or 0)}

    # ------------------------------------------------------------------ operaciones
    def log_op(self, op: str, detail: str = ""):
        with self._cx() as cx:
            cx.execute("INSERT INTO ops(op, at, detail) VALUES (?, ?, ?)", (op, now_iso(), detail))

    def ops_seen(self) -> dict:
        with self._cx() as cx:
            return {r["op"]: r["n"] for r in cx.execute("SELECT op, COUNT(*) AS n FROM ops GROUP BY op")}

    def reset_documents(self):
        with self._cx() as cx:
            cx.execute("DELETE FROM documents")
            cx.execute("DELETE FROM ops")
