from __future__ import annotations
import os
import sqlite3
from pathlib import Path
from typing import Any
from flask import current_app, g
import shutil

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - optional dependency in sqlite-only environments
    psycopg = None
    dict_row = None


class DBCursor:
    def __init__(self, cursor: Any, backend: str, conn: Any, statement: str):
        self._cursor = cursor
        self._backend = backend
        self._conn = conn
        self._statement = statement
        self.lastrowid = getattr(cursor, 'lastrowid', None)
        if self._backend == 'postgres':
            self.lastrowid = self._resolve_lastrowid()

    def _resolve_lastrowid(self) -> int | None:
        text = self._statement.strip().lower()
        if not text.startswith('insert') or 'returning' in text:
            return None
        try:
            with self._conn.cursor() as c:
                c.execute('SELECT LASTVAL()')
                row = c.fetchone()
                if not row:
                    return None
                if isinstance(row, dict):
                    return next(iter(row.values()))
                return row[0]
        except Exception:
            return None

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class DBConnection:
    def __init__(self, conn: Any, backend: str):
        self._conn = conn
        self.backend = backend

    def _adapt_sql(self, sql: str) -> str:
        if self.backend == 'sqlite':
            return sql
        return sql.replace('?', '%s')

    def execute(self, sql: str, params: tuple | list = ()):
        statement = self._adapt_sql(sql)
        if self.backend == 'sqlite':
            cur = self._conn.execute(statement, params)
            return DBCursor(cur, self.backend, self._conn, statement)
        cur = self._conn.cursor()
        cur.execute(statement, params)
        return DBCursor(cur, self.backend, self._conn, statement)

    def executemany(self, sql: str, params_seq: list[tuple] | tuple[tuple, ...]):
        statement = self._adapt_sql(sql)
        if self.backend == 'sqlite':
            self._conn.executemany(statement, params_seq)
            return
        with self._conn.cursor() as cur:
            cur.executemany(statement, params_seq)

    def executescript(self, script: str):
        if self.backend == 'sqlite':
            self._conn.executescript(script)
            return
        statements: list[str] = []
        chunk: list[str] = []
        for line in script.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('--'):
                continue
            chunk.append(line)
            if stripped.endswith(';'):
                statements.append('\n'.join(chunk))
                chunk = []
        if chunk:
            statements.append('\n'.join(chunk))
        with self._conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def db_backend() -> str:
    return 'postgres' if os.environ.get('DATABASE_URL', '').strip() else 'sqlite'


def get_db() -> DBConnection:
    if 'db' not in g:
        backend = db_backend()
        if backend == 'postgres':
            if psycopg is None:
                raise RuntimeError('psycopg is required when DATABASE_URL is set')
            conn = psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row)
            g.db = DBConnection(conn, backend='postgres')
        else:
            db_path = Path(current_app.instance_path) / 'mbarete_erp.sqlite3'
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys = ON;')
            g.db = DBConnection(conn, backend='sqlite')
    return g.db


def close_db(_: object = None) -> None:
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db(app_version: str, schema_version: str, backups_root: Path) -> None:
    db = get_db()
    schema_name = 'schema_postgres.sql' if db.backend == 'postgres' else 'schema.sql'
    schema_path = Path(current_app.root_path) / schema_name
    if db.backend == 'sqlite':
        db_path = Path(current_app.instance_path) / 'mbarete_erp.sqlite3'
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


def _get_meta_value(db: DBConnection, key: str) -> str | None:
    try:
        row = db.execute('SELECT value FROM app_meta WHERE key = ?', (key,)).fetchone()
        if not row:
            return None
        if isinstance(row, dict):
            return row.get('value')
        return row['value']
    except Exception:
        return None


def _ensure_columns(db: DBConnection) -> None:
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
    _ensure_table_columns(db, 'users', {
        'active': 'ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1',
        'last_login_at': 'ALTER TABLE users ADD COLUMN last_login_at TEXT',
    })


def _ensure_table_columns(db: DBConnection, table: str, wanted: dict[str, str]) -> None:
    existing: set[str] = set()
    try:
        if db.backend == 'sqlite':
            existing = {row[1] for row in db.execute(f'PRAGMA table_info({table})').fetchall()}
        else:
            rows = db.execute(
                '''
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = ?
                ''',
                (table,),
            ).fetchall()
            existing = {row['column_name'] if isinstance(row, dict) else row[0] for row in rows}
    except Exception:
        existing = set()
    for column, statement in wanted.items():
        if column not in existing:
            db.execute(statement)
