from __future__ import annotations
from datetime import datetime
from pathlib import Path
import os
import re
from slugify import slugify

PROJECT_SUBFOLDERS = [
    '01_Documentos',
    '02_Materiales_del_Cliente',
    '03_Diseno_y_Desarrollo/preview_v1',
    '03_Diseno_y_Desarrollo/preview_v2',
    '03_Diseno_y_Desarrollo/version_final',
    '03_Diseno_y_Desarrollo/capturas_pantalla',
    '03_Diseno_y_Desarrollo/archivos_fuente',
    '04_Dominio_y_Hosting',
    '05_SEO_y_Analytics',
    '06_Comunicaciones',
    '07_Entregables_Finales',
]


def sanitize_name(value: str) -> str:
    return slugify(value or '', separator='_').replace('-', '_')


def format_project_folder_name(start_date: str | None, business_name: str, plan: str) -> str:
    dt = datetime.strptime(start_date, '%Y-%m-%d') if start_date else datetime.now()
    prefix = dt.strftime('%Y-%m')
    business = re.sub(r'[\/:*?"<>|]+', '', (business_name or '').strip()) or 'Cliente'
    plan_label = re.sub(r'[\/:*?"<>|]+', '', (plan or '').strip()) or 'Plan'
    return f"{prefix}_{sanitize_name(business)}_{sanitize_name(plan_label)}"


def ensure_project_structure(base_root: str | os.PathLike[str], folder_name: str) -> Path:
    root = Path(base_root) / folder_name
    root.mkdir(parents=True, exist_ok=True)
    for sub in PROJECT_SUBFOLDERS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def next_code(prefix: str, current_id: int) -> str:
    return f"{prefix}-{current_id:04d}"


def guarani(value: int | None) -> str:
    value = int(value or 0)
    return f"Gs. {value:,.0f}".replace(',', '.')


def money_display(value, currency_code: str = 'PYG', exchange_rate: int | float = 7800) -> str:
    amount = float(value or 0)
    currency = (currency_code or 'PYG').upper()
    if currency == 'USD':
        rate = float(exchange_rate or 1)
        usd = amount / rate if rate else 0
        return f"USD {usd:,.2f}"
    return guarani(round(amount))
