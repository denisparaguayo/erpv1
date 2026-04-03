from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_FILE = Path.home() / '.mbarete_erp_config.json'
DEFAULT_DATA_DIR = Path.home() / 'MbareteERPData'
SERVER_DEFAULT_DATA_DIR = Path('/data')


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {'data_path': str(DEFAULT_DATA_DIR)}


def save_config(config: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')


def expected_db_path(data_root: Path) -> Path:
    return data_root / 'instance' / 'mbarete_erp.sqlite3'


def looks_like_data_folder(folder: Path) -> bool:
    if not folder.exists() or not folder.is_dir():
        return False
    db_path = expected_db_path(folder)
    projects = folder / 'Proyectos'
    backups = folder / 'backups'
    return db_path.exists() or projects.exists() or backups.exists()


def choose_directory_gui() -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        selected = filedialog.askdirectory(title='Seleccioná la carpeta MbareteERPData')
        root.destroy()
        return Path(selected) if selected else None
    except Exception:
        return None


def _running_in_server_mode() -> bool:
    return os.environ.get('MBARETE_SERVER_MODE', '0') == '1' or os.environ.get('COOLIFY_FQDN') is not None


def resolve_data_root() -> Path:
    env_override = os.environ.get('MBARETE_ERP_DATA_DIR')
    if env_override:
        path = Path(env_override).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path

    if _running_in_server_mode():
        SERVER_DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)
        return SERVER_DEFAULT_DATA_DIR

    config = load_config()
    configured_path = Path(config.get('data_path') or DEFAULT_DATA_DIR).expanduser()

    if configured_path.exists() and (looks_like_data_folder(configured_path) or not expected_db_path(configured_path).exists()):
        configured_path.mkdir(parents=True, exist_ok=True)
        save_config({'data_path': str(configured_path)})
        return configured_path

    print('\n[Mbarete ERP] No se encontró la carpeta de datos configurada.')
    print(f'Ruta actual: {configured_path}')
    print('Opciones:')
    print('  1) Seleccionar carpeta existente')
    print('  2) Crear una nueva carpeta de datos')
    choice = input('Elegí una opción [1/2] (Enter = 2): ').strip() or '2'

    selected: Path | None = None
    if choice == '1':
        selected = choose_directory_gui()
        if selected is None:
            manual = input('No se pudo abrir el selector. Pegá la ruta manualmente: ').strip()
            selected = Path(manual).expanduser() if manual else None
        if selected and not selected.exists():
            print('La carpeta indicada no existe. Se usará una nueva carpeta por defecto.')
            selected = None
        if selected and not looks_like_data_folder(selected):
            print('La carpeta no parece una carpeta de datos válida de Mbarete ERP. Igual se usará y se completará la estructura.')
    if selected is None:
        default_new = DEFAULT_DATA_DIR
        target = input(f'Ruta nueva de datos [{default_new}]: ').strip()
        selected = Path(target).expanduser() if target else default_new
        selected.mkdir(parents=True, exist_ok=True)

    save_config({'data_path': str(selected)})
    return selected
