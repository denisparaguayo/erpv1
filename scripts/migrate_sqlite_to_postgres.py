from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

TABLES = [
    'app_meta',
    'users',
    'settings',
    'payment_methods',
    'payment_conditions',
    'service_catalog',
    'clients',
    'projects',
    'project_services',
    'budgets',
    'budget_items',
    'payments',
    'invoice_items',
    'project_files',
    'html_versions',
    'renewals',
    'activities',
]


def read_rows(sqlite_conn: sqlite3.Connection, table: str) -> tuple[list[str], list[tuple]]:
    cols = [row[1] for row in sqlite_conn.execute(f'PRAGMA table_info({table})').fetchall()]
    if not cols:
        return [], []
    rows = sqlite_conn.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
    return cols, rows


def main() -> None:
    sqlite_path = os.environ.get('SQLITE_PATH', 'instance/mbarete_erp.sqlite3')
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise SystemExit('DATABASE_URL is required')

    source = Path(sqlite_path)
    if not source.exists():
        raise SystemExit(f'SQLite file not found: {source}')

    sqlite_conn = sqlite3.connect(source)
    pg_conn = psycopg.connect(database_url, row_factory=dict_row)

    try:
        with pg_conn.cursor() as cur:
            for table in reversed(TABLES):
                cur.execute(f'TRUNCATE TABLE {table} RESTART IDENTITY CASCADE;')

        for table in TABLES:
            cols, rows = read_rows(sqlite_conn, table)
            if not cols:
                print(f'- skip {table}: not found in SQLite')
                continue
            if rows:
                placeholders = ', '.join(['%s'] * len(cols))
                sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
                with pg_conn.cursor() as cur:
                    cur.executemany(sql, rows)
            print(f'- {table}: {len(rows)} rows')

        with pg_conn.cursor() as cur:
            for table in TABLES:
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema='public' AND table_name=%s AND column_name='id'
                    """,
                    (table,),
                )
                if cur.fetchone():
                    cur.execute(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 1), true)"
                    )

        pg_conn.commit()
        print('\nMigration completed successfully.')
    finally:
        sqlite_conn.close()
        pg_conn.close()


if __name__ == '__main__':
    main()
