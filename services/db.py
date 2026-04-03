from __future__ import annotations
import shutil
import sqlite3
from pathlib import Path
from flask import current_app, g


def get_db() -> sqlite3.Connection:
    if 'db' not in g:
        db_path = Path(current_app.instance_path) / 'mbarete_erp.sqlite3'
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON;')
        g.db = conn
    return g.db


def close_db(_: object = None) -> None:
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db(app_version: str, schema_version: str, backups_root: Path) -> None:
    db = get_db()
    db_path = Path(current_app.instance_path) / 'mbarete_erp.sqlite3'
    schema_path = Path(current_app.root_path) / 'schema.sql'
    existed = db_path.exists() and db_path.stat().st_size > 0
    old_schema = _get_meta_value(db, 'schema_version')
    if existed and old_schema != schema_version:
        backups_root.mkdir(parents=True, exist_ok=True)
        backup_path = backups_root / f"pre_update_{old_schema or 'legacy'}_to_{schema_version}_{_timestamp()}.sqlite3"
        shutil.copy2(db_path, backup_path)
    db.executescript(schema_path.read_text(encoding='utf-8'))
    _ensure_columns(db)
    db.execute("INSERT INTO app_meta (key, value) VALUES ('app_version', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (app_version,))
    db.execute("INSERT INTO app_meta (key, value) VALUES ('schema_version', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (schema_version,))
    db.commit()


def _timestamp() -> str:
    from datetime import datetime
    return datetime.now().strftime('%Y%m%d_%H%M%S')


def _get_meta_value(db: sqlite3.Connection, key: str) -> str | None:
    try:
        row = db.execute('SELECT value FROM app_meta WHERE key = ?', (key,)).fetchone()
        return row['value'] if row else None
    except sqlite3.OperationalError:
        return None


def _ensure_columns(db: sqlite3.Connection) -> None:
    _ensure_table_columns(db, 'payments', {
        'service_items': 'ALTER TABLE payments ADD COLUMN service_items TEXT',
        'service_amount': 'ALTER TABLE payments ADD COLUMN service_amount INTEGER NOT NULL DEFAULT 0',
        'extra_items': 'ALTER TABLE payments ADD COLUMN extra_items TEXT',
        'extra_amount': 'ALTER TABLE payments ADD COLUMN extra_amount INTEGER NOT NULL DEFAULT 0',
        'domain_charge': 'ALTER TABLE payments ADD COLUMN domain_charge INTEGER DEFAULT 0',
        'observations': 'ALTER TABLE payments ADD COLUMN observations TEXT',
        'pdf_path': 'ALTER TABLE payments ADD COLUMN pdf_path TEXT',
        'currency_code': "ALTER TABLE payments ADD COLUMN currency_code TEXT NOT NULL DEFAULT 'PYG'",
        'exchange_rate': 'ALTER TABLE payments ADD COLUMN exchange_rate REAL NOT NULL DEFAULT 1',
        'paid_date': 'ALTER TABLE payments ADD COLUMN paid_date TEXT',
    })
    _ensure_table_columns(db, 'project_files', {
        'purpose': "ALTER TABLE project_files ADD COLUMN purpose TEXT NOT NULL DEFAULT 'Documento'",
    })
    _ensure_table_columns(db, 'projects', {
        'main_service_id': 'ALTER TABLE projects ADD COLUMN main_service_id INTEGER',
        'domain_provider': 'ALTER TABLE projects ADD COLUMN domain_provider TEXT',
        'domain_status': 'ALTER TABLE projects ADD COLUMN domain_status TEXT',
        'domain_user': 'ALTER TABLE projects ADD COLUMN domain_user TEXT',
        'domain_password': 'ALTER TABLE projects ADD COLUMN domain_password TEXT',
        'client_has_domain': 'ALTER TABLE projects ADD COLUMN client_has_domain INTEGER NOT NULL DEFAULT 0',
        'hosting_status': 'ALTER TABLE projects ADD COLUMN hosting_status TEXT',
        'hosting_user': 'ALTER TABLE projects ADD COLUMN hosting_user TEXT',
        'hosting_password': 'ALTER TABLE projects ADD COLUMN hosting_password TEXT',
        'external_hosting': 'ALTER TABLE projects ADD COLUMN external_hosting INTEGER NOT NULL DEFAULT 0',
        'technical_notes': 'ALTER TABLE projects ADD COLUMN technical_notes TEXT',
    })
    _ensure_table_columns(db, 'service_catalog', {
        'service_kind': "ALTER TABLE service_catalog ADD COLUMN service_kind TEXT NOT NULL DEFAULT 'extra'",
    })


def _ensure_table_columns(db: sqlite3.Connection, table: str, wanted: dict[str, str]) -> None:
    try:
        existing = {row[1] for row in db.execute(f'PRAGMA table_info({table})').fetchall()}
    except sqlite3.OperationalError:
        existing = set()
    for column, statement in wanted.items():
        if column not in existing:
            db.execute(statement)
