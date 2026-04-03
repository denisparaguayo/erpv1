from __future__ import annotations
from datetime import date, datetime
from functools import wraps
from pathlib import Path
import json
import os
import shutil
import subprocess

from flask import Flask, flash, g, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from services.db import close_db, db_backend, get_db, init_db
from services.pdf_generator import create_invoice_pdf
from services.utils import ensure_project_structure, format_project_folder_name, guarani, money_display, next_code, sanitize_name
from services.config_manager import CONFIG_FILE, resolve_data_root
from werkzeug.middleware.proxy_fix import ProxyFix

APP_VERSION = '3.5.1'
SCHEMA_VERSION = '3.6.0'
DATA_ROOT = Path(os.environ.get('MBARETE_ERP_DATA_DIR', resolve_data_root()))
INSTANCE_DIR = DATA_ROOT / 'instance'
PROJECTS_ROOT = DATA_ROOT / 'Proyectos'
UPLOADS_ROOT = DATA_ROOT / 'uploads'
BACKUPS_ROOT = DATA_ROOT / 'backups'
SETTINGS_ROOT = DATA_ROOT / 'settings'
ALLOWED_UPLOADS = {'.pdf', '.png', '.jpg', '.jpeg', '.docx', '.txt', '.xlsx', '.html', '.css', '.js', '.svg', '.webp'}
FILE_CATEGORIES = ['Documento', 'Logo cliente', 'Material cliente', 'Contrato', 'Factura', 'Recibo', 'SEO', 'Comunicación', 'Entregable']

DEFAULT_SETTINGS = {
    'agency_name': 'Mbarete Digital',
    'agency_subtitle': 'Agencia de Diseño Web',
    'agency_location': 'Asunción, Paraguay',
    'agency_ruc': '',
    'agency_address': '',
    'agency_phone': '0986 550 235',
    'agency_whatsapp': '0986 550 235',
    'agency_email': 'hola@mbaretedigital.com.py',
    'agency_website': 'mbaretedigital.com.py',
    'invoice_default_condition': 'Contado',
    'invoice_default_notes': '',
    'vat_percent': '10',
    'next_invoice_number': '1',
    'next_receipt_number': '1',
    'next_budget_number': '1',
    'projects_root': str(PROJECTS_ROOT),
    'backups_root': str(BACKUPS_ROOT),
    'logo_path': '',
    'show_logo_on_invoice': '1',
    'currency_code': 'PYG',
    'usd_exchange_rate': '7800',
}

DEFAULT_SERVICES = [
    ('Página web · Plan Básico', 'Páginas web', 'principal', 'Landing page con WhatsApp, SEO básico y mapa.', 800000),
    ('Página web · Plan Estándar', 'Páginas web', 'principal', 'Sitio con varias secciones, formulario y SEO mejorado.', 1400000),
    ('Página web · Plan Pro', 'Páginas web', 'principal', 'Sitio profesional con páginas internas y blog.', 3800000),
    ('Diseño de logo', 'Branding', 'principal', 'Diseño de logo comercial.', 400000),
    ('Fotografía de productos', 'Fotografía', 'principal', 'Sesión básica de productos para catálogo.', 650000),
    ('Proyecto personalizado', 'Otros', 'principal', 'Proyecto sin servicio principal fijo. Usar extras.', 0),
    ('Catálogo digital / menú', 'Extras web', 'extra', 'Catálogo visual con pedido por WhatsApp.', 400000),
    ('Posicionamiento en Google (SEO Local)', 'SEO', 'extra', 'Trabajo mensual de SEO local.', 320000),
    ('Manejo de redes sociales', 'Marketing', 'extra', 'Gestión mensual de publicaciones.', 450000),
    ('Mantenimiento mensual', 'Mantenimiento', 'extra', 'Cambios y soporte mensual.', 170000),
    ('Email profesional', 'Hosting y dominio', 'extra', 'Correo corporativo anual.', 140000),
]
DEFAULT_PAYMENT_METHODS = [
    ('Efectivo', 'Pago en efectivo', 1),
    ('Transferencia bancaria', 'Transferencia o depósito', 2),
    ('Billetera digital', 'Personal / Tigo Money / QR', 3),
    ('Tarjeta', 'Débito o crédito', 4),
]
DEFAULT_PAYMENT_CONDITIONS = [
    ('Contado', 'Pago completo', 1),
    ('50% anticipo / 50% entrega', 'Mitad al iniciar y mitad al entregar', 2),
    ('Mensual', 'Pago recurrente mensual', 3),
    ('Personalizado', 'Condición negociada', 99),
]

PUBLIC_ENDPOINTS = {'login', 'health', 'static'}
ADMIN_ENDPOINTS = {
    'users_index',
    'users_new',
    'users_toggle',
    'settings_page',
    'settings_logo_delete',
    'settings_general_save',
    'payment_methods_add',
    'payment_methods_toggle',
    'payment_methods_delete',
    'payment_conditions_add',
    'payment_conditions_toggle',
    'payment_conditions_delete',
    'services_form',
    'services_delete',
    'download_backup',
}


def create_app() -> Flask:
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('MBARETE_SECRET_KEY', 'change-this-in-production')
    app.config['PREFERRED_URL_SCHEME'] = os.environ.get('MBARETE_URL_SCHEME', 'https')
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('MBARETE_SESSION_SECURE', '1') == '1'
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
    app.instance_path = str(INSTANCE_DIR)
    for folder in [INSTANCE_DIR, PROJECTS_ROOT, UPLOADS_ROOT, BACKUPS_ROOT, SETTINGS_ROOT]:
        folder.mkdir(parents=True, exist_ok=True)

    app.teardown_appcontext(close_db)

    @app.context_processor
    def inject_helpers():
        db = get_db()
        return {
            'gs': guarani,
            'money': money_display,
            'today': date.today().isoformat(),
            'data_root': str(DATA_ROOT),
            'config_file': str(CONFIG_FILE),
            'app_version': APP_VERSION,
            'settings': get_settings(db),
            'current_user': getattr(g, 'current_user', None),
        }

    @app.before_request
    def setup() -> None:
        if not getattr(g, '_db_ready', False):
            init_db(APP_VERSION, SCHEMA_VERSION, BACKUPS_ROOT)
            ensure_defaults()
            g._db_ready = True
        g.current_user = current_user()
        endpoint = request.endpoint or ''
        if not endpoint:
            return
        if endpoint in PUBLIC_ENDPOINTS or endpoint.startswith('static'):
            return
        if not g.current_user:
            return redirect(url_for('login', next=request.path))
        if endpoint in ADMIN_ENDPOINTS and g.current_user['role'] != 'admin':
            flash('Solo el administrador puede realizar esa acción.', 'error')
            return redirect(url_for('dashboard'))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            email = (request.form.get('email') or '').strip().lower()
            password = request.form.get('password') or ''
            db = get_db()
            user = db.execute('SELECT * FROM users WHERE email = ? AND active = 1', (email,)).fetchone()
            if user and check_password_hash(user['password_hash'], password):
                session['user_id'] = user['id']
                db.execute('UPDATE users SET last_login_at = ? WHERE id = ?', (datetime.now().isoformat(timespec='seconds'), user['id']))
                db.commit()
                next_path = request.args.get('next') or url_for('dashboard')
                if not next_path.startswith('/'):
                    next_path = url_for('dashboard')
                return redirect(next_path)
            flash('Credenciales inválidas.', 'error')
        return render_template('login.html')

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.get('/users')
    @admin_required
    def users_index():
        db = get_db()
        users = db.execute('SELECT id, email, role, active, created_at, last_login_at FROM users ORDER BY id').fetchall()
        return render_template('users.html', users=users)

    @app.route('/users/new', methods=['GET', 'POST'])
    @admin_required
    def users_new():
        if request.method == 'POST':
            db = get_db()
            email = (request.form.get('email') or '').strip().lower()
            password = request.form.get('password') or ''
            role = (request.form.get('role') or 'user').strip().lower()
            if role not in {'admin', 'user'}:
                role = 'user'
            if not email or not password:
                flash('Email y contraseña son obligatorios.', 'error')
                return render_template('user_form.html')
            exists = db.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
            if exists:
                flash('Ese email ya existe.', 'error')
                return render_template('user_form.html')
            db.execute(
                'INSERT INTO users (email, password_hash, role, active) VALUES (?, ?, ?, 1)',
                (email, generate_password_hash(password), role),
            )
            db.commit()
            flash('Usuario creado correctamente.', 'success')
            return redirect(url_for('users_index'))
        return render_template('user_form.html')

    @app.post('/users/<int:user_id>/toggle')
    @admin_required
    def users_toggle(user_id: int):
        db = get_db()
        user = db.execute('SELECT id, active, role FROM users WHERE id = ?', (user_id,)).fetchone()
        if not user:
            flash('Usuario no encontrado.', 'error')
            return redirect(url_for('users_index'))
        if user_id == g.current_user['id']:
            flash('No podés desactivar tu propio usuario.', 'error')
            return redirect(url_for('users_index'))
        db.execute('UPDATE users SET active = ? WHERE id = ?', (0 if user['active'] else 1, user_id))
        db.commit()
        flash('Estado de usuario actualizado.', 'success')
        return redirect(url_for('users_index'))


    @app.get('/health')
    def health():
        db = get_db()
        db.execute('SELECT 1')
        return jsonify({'status': 'ok', 'app_version': APP_VERSION, 'schema_version': SCHEMA_VERSION})

    @app.get('/')
    def dashboard():
        db = get_db()
        stats = {
            'clients': scalar(db, 'SELECT COUNT(*) FROM clients'),
            'projects': scalar(db, "SELECT COUNT(*) FROM projects WHERE status NOT IN ('Entregado','Inactivo')"),
            'payments': scalar(db, 'SELECT COUNT(*) FROM payments'),
            'services': scalar(db, 'SELECT COUNT(*) FROM service_catalog WHERE active = 1'),
            'renewals_due': scalar(db, "SELECT COUNT(*) FROM renewals WHERE status = 'Pendiente'"),
            'income_month': scalar(
                db,
                "SELECT COALESCE(SUM(total),0) FROM payments WHERE status = 'Pagado' "
                "AND SUBSTRING(COALESCE(paid_date, issue_date), 1, 7)=?",
                (date.today().strftime('%Y-%m'),),
            ),
        }
        urgent_projects = db.execute('''
            SELECT p.*, c.business_name
            FROM projects p JOIN clients c ON c.id = p.client_id
            WHERE p.status NOT IN ('Entregado','Inactivo')
            ORDER BY COALESCE(p.due_date,'9999-99-99') ASC LIMIT 8
        ''').fetchall()
        pending_payments = db.execute('''
            SELECT p.*, c.business_name
            FROM payments p JOIN projects pr ON pr.id = p.project_id JOIN clients c ON c.id = pr.client_id
            WHERE p.status IN ('Pendiente','Vencido')
            ORDER BY p.issue_date DESC, p.id DESC LIMIT 8
        ''').fetchall()
        renewals = db.execute('''
            SELECT r.*, c.business_name, pr.code as project_code
            FROM renewals r JOIN projects pr ON pr.id = r.project_id JOIN clients c ON c.id = pr.client_id
            WHERE r.status != 'Pagado'
            ORDER BY r.due_date ASC LIMIT 8
        ''').fetchall()
        recent_projects = db.execute('''
            SELECT p.*, c.business_name
            FROM projects p JOIN clients c ON c.id = p.client_id
            ORDER BY p.created_at DESC, p.id DESC LIMIT 6
        ''').fetchall()
        activities = db.execute('''
            SELECT a.*, c.business_name
            FROM activities a LEFT JOIN clients c ON c.id = a.client_id
            ORDER BY a.created_at DESC, a.id DESC LIMIT 10
        ''').fetchall()
        quick = {
            'urgent_count': sum(1 for p in urgent_projects if traffic_status_for_project(p) == 'red'),
            'warning_count': sum(1 for p in urgent_projects if traffic_status_for_project(p) == 'yellow'),
            'pending_amount': scalar(db, "SELECT COALESCE(SUM(total),0) FROM payments WHERE status IN ('Pendiente','Vencido')"),
        }
        return render_template('dashboard.html', stats=stats, urgent_projects=urgent_projects, pending_payments=pending_payments,
                               renewals=renewals, recent_projects=recent_projects, activities=activities, quick=quick,
                               traffic_status_for_project=traffic_status_for_project, traffic_status_for_payment=traffic_status_for_payment,
                               traffic_status_for_renewal=traffic_status_for_renewal, meta=get_app_meta(db))

    @app.get('/backup/download')
    def download_backup():
        if db_backend() == 'postgres':
            flash('Para PostgreSQL usá backup con pg_dump en el servidor.', 'error')
            return redirect(url_for('settings_page'))
        db_path = Path(app.instance_path) / 'mbarete_erp.sqlite3'
        backup_name = f"mbarete_backup_manual_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sqlite3"
        backup_path = BACKUPS_ROOT / backup_name
        shutil.copy2(db_path, backup_path)
        return send_file(backup_path, as_attachment=True, download_name=backup_name)

    @app.get('/settings')
    def settings_page():
        db = get_db()
        settings = get_settings(db)
        methods = db.execute('SELECT * FROM payment_methods ORDER BY sort_order, name').fetchall()
        conditions = db.execute('SELECT * FROM payment_conditions ORDER BY sort_order, name').fetchall()
        return render_template('settings.html', settings=settings, methods=methods, conditions=conditions, meta=get_app_meta(db))

    @app.post('/settings/logo/delete')
    def settings_logo_delete():
        db = get_db()
        logo_path = get_settings(db).get('logo_path', '')
        if logo_path:
            Path(logo_path).unlink(missing_ok=True)
        set_setting(db, 'logo_path', '')
        db.commit()
        flash('Logo eliminado.', 'success')
        return redirect(url_for('settings_page'))

    @app.post('/settings/general')
    def settings_general_save():
        db = get_db()
        current = get_settings(db)
        for key in DEFAULT_SETTINGS:
            if key in {'logo_path', 'projects_root', 'backups_root'}:
                continue
            if key == 'show_logo_on_invoice':
                value = '1' if request.form.get('show_logo_on_invoice') == '1' else '0'
            else:
                value = request.form.get(key, current.get(key, '')).strip()
            set_setting(db, key, value)
        file = request.files.get('logo_file')
        if file and file.filename:
            ext = Path(file.filename).suffix.lower()
            if ext in {'.png', '.jpg', '.jpeg', '.webp', '.svg'}:
                target = SETTINGS_ROOT / f'agency_logo{ext}'
                file.save(target)
                set_setting(db, 'logo_path', str(target))
        db.commit()
        flash('Configuración general actualizada.', 'success')
        return redirect(url_for('settings_page'))

    @app.post('/settings/payment-methods')
    def payment_methods_add():
        add_catalog_row('payment_methods')
        return redirect(url_for('settings_page'))

    @app.post('/settings/payment-methods/<int:row_id>/toggle')
    def payment_methods_toggle(row_id: int):
        toggle_catalog_row('payment_methods', row_id)
        return redirect(url_for('settings_page'))

    @app.post('/settings/payment-methods/<int:row_id>/delete')
    def payment_methods_delete(row_id: int):
        delete_catalog_row('payment_methods', row_id)
        return redirect(url_for('settings_page'))

    @app.post('/settings/payment-conditions')
    def payment_conditions_add():
        add_catalog_row('payment_conditions')
        return redirect(url_for('settings_page'))

    @app.post('/settings/payment-conditions/<int:row_id>/toggle')
    def payment_conditions_toggle(row_id: int):
        toggle_catalog_row('payment_conditions', row_id)
        return redirect(url_for('settings_page'))

    @app.post('/settings/payment-conditions/<int:row_id>/delete')
    def payment_conditions_delete(row_id: int):
        delete_catalog_row('payment_conditions', row_id)
        return redirect(url_for('settings_page'))

    @app.get('/services')
    def services_index():
        db = get_db()
        q = request.args.get('q', '').strip()
        if q:
            like = f'%{q}%'
            services = db.execute('''SELECT * FROM service_catalog WHERE name LIKE ? OR category LIKE ? OR description LIKE ? ORDER BY active DESC, service_kind, category, name''', (like, like, like)).fetchall()
        else:
            services = db.execute('SELECT * FROM service_catalog ORDER BY active DESC, service_kind, category, name').fetchall()
        return render_template('services.html', services=services, q=q)

    @app.route('/services/new', methods=['GET', 'POST'])
    @app.route('/services/<int:service_id>/edit', methods=['GET', 'POST'])
    def services_form(service_id: int | None = None):
        db = get_db()
        service = db.execute('SELECT * FROM service_catalog WHERE id = ?', (service_id,)).fetchone() if service_id else None
        if request.method == 'POST':
            data = {
                'name': request.form.get('name', '').strip(),
                'category': request.form.get('category', '').strip(),
                'service_kind': request.form.get('service_kind', 'extra').strip() or 'extra',
                'description': request.form.get('description', '').strip(),
                'base_price': int(request.form.get('base_price') or 0),
                'active': 1 if request.form.get('active') == '1' else 0,
            }
            if not data['name']:
                flash('El nombre del servicio es obligatorio.', 'error')
                return render_template('service_form.html', service=service)
            if service_id:
                db.execute('''UPDATE service_catalog SET name=:name, category=:category, service_kind=:service_kind, description=:description, base_price=:base_price, active=:active, updated_at=CURRENT_TIMESTAMP WHERE id=:service_id''', {**data, 'service_id': service_id})
            else:
                db.execute('''INSERT INTO service_catalog (name, category, service_kind, description, base_price, active) VALUES (:name,:category,:service_kind,:description,:base_price,:active)''', data)
            db.commit()
            flash('Servicio guardado correctamente.', 'success')
            return redirect(url_for('services_index'))
        return render_template('service_form.html', service=service)

    @app.post('/services/<int:service_id>/delete')
    def services_delete(service_id: int):
        db = get_db()
        db.execute('DELETE FROM service_catalog WHERE id = ?', (service_id,))
        db.commit()
        return redirect(url_for('services_index'))

    @app.get('/clients')
    def clients_index():
        db = get_db()
        q = request.args.get('q', '').strip()
        if q:
            like = f'%{q}%'
            clients = db.execute('''SELECT * FROM clients WHERE business_name LIKE ? OR owner_name LIKE ? OR whatsapp LIKE ? OR code LIKE ? OR email LIKE ? ORDER BY business_name ASC''', (like, like, like, like, like)).fetchall()
        else:
            clients = db.execute('SELECT * FROM clients ORDER BY business_name ASC').fetchall()
        return render_template('clients.html', clients=clients, q=q)

    @app.route('/clients/new', methods=['GET', 'POST'])
    def clients_new():
        db = get_db()
        if request.method == 'POST':
            data = parse_client_form(request)
            cur = db.execute('''INSERT INTO clients (business_name, category, owner_name, whatsapp, phone, email, address, city, ruc_ci, instagram, facebook, status) VALUES (:business_name,:category,:owner_name,:whatsapp,:phone,:email,:address,:city,:ruc_ci,:instagram,:facebook,:status)''', data)
            client_id = cur.lastrowid
            code = next_code('CLI', client_id)
            db.execute('UPDATE clients SET code = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (code, client_id))
            log_activity(db, client_id, None, 'Cliente creado', f"Cliente {data['business_name']} registrado")
            db.commit()
            return redirect(url_for('client_detail', client_id=client_id))
        return render_template('client_form.html', client=None)

    @app.route('/clients/<int:client_id>/edit', methods=['GET', 'POST'])
    def clients_edit(client_id: int):
        db = get_db(); client = db.execute('SELECT * FROM clients WHERE id = ?', (client_id,)).fetchone()
        if not client: return redirect(url_for('clients_index'))
        if request.method == 'POST':
            data = parse_client_form(request)
            db.execute('''UPDATE clients SET business_name=:business_name, category=:category, owner_name=:owner_name, whatsapp=:whatsapp, phone=:phone, email=:email, address=:address, city=:city, ruc_ci=:ruc_ci, instagram=:instagram, facebook=:facebook, status=:status, updated_at=CURRENT_TIMESTAMP WHERE id=:client_id''', {**data, 'client_id': client_id})
            log_activity(db, client_id, None, 'Cliente editado', f"Cliente {data['business_name']} actualizado")
            db.commit(); return redirect(url_for('client_detail', client_id=client_id))
        return render_template('client_form.html', client=client)

    @app.post('/clients/<int:client_id>/delete')
    def clients_delete(client_id: int):
        db = get_db(); db.execute('DELETE FROM clients WHERE id = ?', (client_id,)); db.commit(); return redirect(url_for('clients_index'))

    @app.get('/clients/<int:client_id>')
    def client_detail(client_id: int):
        db = get_db()
        client = db.execute('SELECT * FROM clients WHERE id = ?', (client_id,)).fetchone()
        projects = db.execute('SELECT * FROM projects WHERE client_id = ? ORDER BY created_at DESC', (client_id,)).fetchall()
        budgets = db.execute('SELECT * FROM budgets WHERE client_id = ? ORDER BY created_at DESC', (client_id,)).fetchall()
        return render_template('client_detail.html', client=client, projects=projects, budgets=budgets)

    @app.get('/budgets')
    def budgets_index():
        db = get_db()
        q = request.args.get('q', '').strip()
        if q:
            like = f'%{q}%'
            budgets = db.execute('''SELECT b.*, c.business_name, s.name AS main_service_name FROM budgets b JOIN clients c ON c.id=b.client_id LEFT JOIN service_catalog s ON s.id=b.main_service_id WHERE b.code LIKE ? OR c.business_name LIKE ? OR COALESCE(b.title,'') LIKE ? ORDER BY b.created_at DESC''', (like, like, like)).fetchall()
        else:
            budgets = db.execute('''SELECT b.*, c.business_name, s.name AS main_service_name FROM budgets b JOIN clients c ON c.id=b.client_id LEFT JOIN service_catalog s ON s.id=b.main_service_id ORDER BY b.created_at DESC''').fetchall()
        return render_template('budgets.html', budgets=budgets, q=q)

    @app.route('/budgets/new', methods=['GET', 'POST'])
    @app.route('/budgets/<int:budget_id>/edit', methods=['GET', 'POST'])
    def budgets_form(budget_id: int | None = None):
        db = get_db()
        budget = db.execute('SELECT * FROM budgets WHERE id = ?', (budget_id,)).fetchone() if budget_id else None
        clients = db.execute('SELECT id, business_name FROM clients ORDER BY business_name').fetchall()
        services = active_services(db)
        conditions = active_payment_conditions(db)
        budget_items = db.execute('SELECT * FROM budget_items WHERE budget_id = ? ORDER BY id', (budget_id,)).fetchall() if budget_id else []
        if request.method == 'POST':
            payload = parse_scope_form(request, db, 'budget')
            if budget_id:
                db.execute('''UPDATE budgets SET client_id=:client_id, main_service_id=:main_service_id, title=:title, total_amount=:total_amount, payment_condition=:payment_condition, status=:status, notes=:notes, updated_at=CURRENT_TIMESTAMP WHERE id=:scope_id''', payload)
                db.execute('DELETE FROM budget_items WHERE budget_id = ?', (budget_id,))
                scope_id = budget_id
            else:
                cur = db.execute('''INSERT INTO budgets (client_id, main_service_id, title, total_amount, payment_condition, status, notes) VALUES (:client_id,:main_service_id,:title,:total_amount,:payment_condition,:status,:notes)''', payload)
                scope_id = cur.lastrowid
                db.execute('UPDATE budgets SET code = ? WHERE id = ?', (next_code('PRES', scope_id), scope_id))
            save_budget_items(db, scope_id, payload['items'])
            db.commit(); flash('Presupuesto guardado.', 'success')
            return redirect(url_for('budget_detail', budget_id=scope_id))
        return render_template('budget_form.html', budget=budget, clients=clients, services=services, conditions=conditions, budget_items=budget_items)

    @app.get('/budgets/<int:budget_id>')
    def budget_detail(budget_id: int):
        db = get_db()
        budget = db.execute('''SELECT b.*, c.business_name, c.owner_name, s.name AS main_service_name FROM budgets b JOIN clients c ON c.id=b.client_id LEFT JOIN service_catalog s ON s.id=b.main_service_id WHERE b.id = ?''', (budget_id,)).fetchone()
        items = db.execute('SELECT * FROM budget_items WHERE budget_id = ? ORDER BY id', (budget_id,)).fetchall()
        return render_template('budget_detail.html', budget=budget, items=items)

    @app.post('/budgets/<int:budget_id>/delete')
    def budgets_delete(budget_id: int):
        db = get_db(); db.execute('DELETE FROM budgets WHERE id = ?', (budget_id,)); db.commit(); return redirect(url_for('budgets_index'))

    @app.post('/budgets/<int:budget_id>/convert')
    def budget_convert(budget_id: int):
        db = get_db()
        budget = db.execute('SELECT * FROM budgets WHERE id = ?', (budget_id,)).fetchone()
        client = db.execute('SELECT * FROM clients WHERE id = ?', (budget['client_id'],)).fetchone()
        items = db.execute('SELECT * FROM budget_items WHERE budget_id = ? ORDER BY id', (budget_id,)).fetchall()
        main_item = next((i for i in items if i['item_role'] == 'principal'), None)
        main_name = main_item['service_name'] if main_item else (budget['title'] or 'Proyecto personalizado')
        folder_name = format_project_folder_name(date.today().isoformat(), client['business_name'], main_name)
        folder_path = ensure_project_structure(PROJECTS_ROOT, folder_name)
        cur = db.execute('''INSERT INTO projects (client_id, main_service_id, plan, extras, total_amount, payment_condition, status, start_date, notes, folder_path) VALUES (?, ?, ?, ?, ?, ?, 'En desarrollo', ?, ?, ?)''',
                         (budget['client_id'], budget['main_service_id'], main_name, extras_text_from_items(items), budget['total_amount'], budget['payment_condition'], date.today().isoformat(), budget['notes'], str(folder_path)))
        project_id = cur.lastrowid
        code = next_code('PROJ', project_id)
        db.execute('UPDATE projects SET code = ? WHERE id = ?', (code, project_id))
        save_project_items(db, project_id, [{
            'service_id': i['service_id'], 'item_role': i['item_role'], 'service_name': i['service_name'],
            'applied_price': i['applied_price'], 'quantity': i['quantity'], 'line_total': i['line_total']
        } for i in items])
        create_master_note(folder_path, client, {'plan': main_name, 'extras': extras_text_from_items(items), 'total_amount': budget['total_amount'], 'start_date': date.today().isoformat(), 'due_date': '', 'domain_name': '', 'hosting_provider': '', 'status': 'En desarrollo'})
        db.execute("UPDATE budgets SET status = 'Convertido', updated_at=CURRENT_TIMESTAMP WHERE id = ?", (budget_id,))
        log_activity(db, budget['client_id'], project_id, 'Proyecto creado desde presupuesto', f"{main_name} generado desde {budget['code']}")
        db.commit()
        flash('Presupuesto convertido a proyecto.', 'success')
        return redirect(url_for('project_detail', project_id=project_id))

    @app.get('/projects')
    def projects_index():
        db = get_db(); q = request.args.get('q', '').strip()
        if q:
            like = f'%{q}%'
            projects = db.execute('''SELECT p.*, c.business_name FROM projects p JOIN clients c ON c.id = p.client_id WHERE p.code LIKE ? OR c.business_name LIKE ? OR p.plan LIKE ? OR COALESCE(p.domain_name,'') LIKE ? OR COALESCE(p.status,'') LIKE ? ORDER BY p.created_at DESC''', (like, like, like, like, like)).fetchall()
        else:
            projects = db.execute('''SELECT p.*, c.business_name FROM projects p JOIN clients c ON c.id = p.client_id ORDER BY p.created_at DESC''').fetchall()
        return render_template('projects.html', projects=projects, q=q, traffic_status_for_project=traffic_status_for_project)

    @app.route('/projects/new', methods=['GET', 'POST'])
    @app.route('/projects/<int:project_id>/edit', methods=['GET', 'POST'])
    def projects_form(project_id: int | None = None):
        db = get_db()
        project = db.execute('SELECT * FROM projects WHERE id = ?', (project_id,)).fetchone() if project_id else None
        clients = db.execute('SELECT id, business_name FROM clients ORDER BY business_name').fetchall()
        services = active_services(db)
        conditions = active_payment_conditions(db)
        project_items = db.execute('SELECT * FROM project_services WHERE project_id = ? ORDER BY id', (project_id,)).fetchall() if project_id else []
        if request.method == 'POST':
            payload = parse_scope_form(request, db, 'project')
            client = db.execute('SELECT * FROM clients WHERE id = ?', (payload['client_id'],)).fetchone()
            main_name = payload['plan']
            if project_id:
                old_project = project
                payload.update({'scope_id': project_id})
                db.execute('''UPDATE projects SET client_id=:client_id, main_service_id=:main_service_id, plan=:plan, extras=:extras, total_amount=:total_amount, payment_condition=:payment_condition, status=:status, start_date=:start_date, due_date=:due_date, domain_name=:domain_name, domain_provider=:domain_provider, domain_status=:domain_status, domain_user=:domain_user, domain_password=:domain_password, domain_expiry=:domain_expiry, client_has_domain=:client_has_domain, hosting_provider=:hosting_provider, hosting_status=:hosting_status, hosting_user=:hosting_user, hosting_password=:hosting_password, hosting_expiry=:hosting_expiry, external_hosting=:external_hosting, notes=:notes, technical_notes=:technical_notes, updated_at=CURRENT_TIMESTAMP WHERE id=:scope_id''', payload)
                folder_path = Path(old_project['folder_path'])
                db.execute('DELETE FROM project_services WHERE project_id = ?', (project_id,))
                scope_id = project_id
            else:
                folder_name = format_project_folder_name(payload['start_date'], client['business_name'], main_name)
                folder_path = ensure_project_structure(PROJECTS_ROOT, folder_name)
                payload['folder_path'] = str(folder_path)
                cur = db.execute('''INSERT INTO projects (client_id, main_service_id, plan, extras, total_amount, payment_condition, status, start_date, due_date, domain_name, domain_provider, domain_status, domain_user, domain_password, domain_expiry, client_has_domain, hosting_provider, hosting_status, hosting_user, hosting_password, hosting_expiry, external_hosting, notes, technical_notes, folder_path) VALUES (:client_id,:main_service_id,:plan,:extras,:total_amount,:payment_condition,:status,:start_date,:due_date,:domain_name,:domain_provider,:domain_status,:domain_user,:domain_password,:domain_expiry,:client_has_domain,:hosting_provider,:hosting_status,:hosting_user,:hosting_password,:hosting_expiry,:external_hosting,:notes,:technical_notes,:folder_path)''', payload)
                scope_id = cur.lastrowid
                db.execute('UPDATE projects SET code = ? WHERE id = ?', (next_code('PROJ', scope_id), scope_id))
            save_project_items(db, scope_id, payload['items'])
            create_master_note(folder_path, client, payload)
            create_domain_hosting_note(folder_path, client, payload)
            log_activity(db, payload['client_id'], scope_id, 'Proyecto guardado', f"{payload['plan']} · estado {payload['status']}")
            db.commit(); flash('Proyecto guardado correctamente.', 'success')
            return redirect(url_for('project_detail', project_id=scope_id))
        return render_template('project_form.html', clients=clients, project=project, services=services, conditions=conditions, project_items=project_items)

    @app.post('/projects/<int:project_id>/delete')
    def projects_delete(project_id: int):
        db = get_db(); project = db.execute('SELECT * FROM projects WHERE id = ?', (project_id,)).fetchone();
        if project: db.execute('DELETE FROM projects WHERE id = ?', (project_id,)); db.commit(); flash('Proyecto eliminado de la base.', 'success')
        return redirect(url_for('projects_index'))

    @app.get('/projects/<int:project_id>')
    def project_detail(project_id: int):
        db = get_db()
        project = db.execute('''SELECT p.*, c.business_name, c.owner_name, c.whatsapp, c.email, c.ruc_ci FROM projects p JOIN clients c ON c.id = p.client_id WHERE p.id = ?''', (project_id,)).fetchone()
        payments = db.execute('SELECT * FROM payments WHERE project_id = ? ORDER BY created_at DESC', (project_id,)).fetchall()
        files = db.execute('SELECT * FROM project_files WHERE project_id = ? ORDER BY created_at DESC', (project_id,)).fetchall()
        versions = db.execute('SELECT * FROM html_versions WHERE project_id = ? ORDER BY version_number DESC', (project_id,)).fetchall()
        renewals = db.execute('SELECT * FROM renewals WHERE project_id = ? ORDER BY due_date ASC', (project_id,)).fetchall()
        activities = db.execute('SELECT * FROM activities WHERE project_id = ? ORDER BY created_at DESC, id DESC', (project_id,)).fetchall()
        service_catalog = active_services(db)
        payment_methods = db.execute('SELECT * FROM payment_methods WHERE active = 1 ORDER BY sort_order, name').fetchall()
        payment_conditions = active_payment_conditions(db)
        project_items = db.execute('SELECT * FROM project_services WHERE project_id = ? ORDER BY item_role DESC, id', (project_id,)).fetchall()
        payment_items = {row['id']: db.execute('SELECT * FROM invoice_items WHERE payment_id = ? ORDER BY id', (row['id'],)).fetchall() for row in payments}
        return render_template('project_detail.html', project=project, payments=payments, payment_items=payment_items, files=files, versions=versions, renewals=renewals, activities=activities, service_catalog=service_catalog, payment_methods=payment_methods, payment_conditions=payment_conditions, project_items=project_items, traffic_status_for_project=traffic_status_for_project, traffic_status_for_payment=traffic_status_for_payment, traffic_status_for_renewal=traffic_status_for_renewal)

    @app.post('/projects/<int:project_id>/open-folder')
    def open_project_folder(project_id: int):
        db = get_db(); project = db.execute('SELECT * FROM projects WHERE id = ?', (project_id,)).fetchone(); folder_path = Path(project['folder_path'])
        try:
            if os.name == 'nt':
                os.startfile(str(folder_path))  # type: ignore[attr-defined]
            elif shutil.which('open'):
                subprocess.Popen(['open', str(folder_path)])
            elif shutil.which('xdg-open'):
                subprocess.Popen(['xdg-open', str(folder_path)])
            else:
                raise RuntimeError('No se pudo detectar un abridor de carpetas.')
            flash('Se intentó abrir la carpeta del proyecto.', 'success')
        except Exception:
            flash(f'No se pudo abrir automáticamente. Ruta: {folder_path}', 'error')
        return redirect(url_for('project_detail', project_id=project_id))

    @app.post('/projects/<int:project_id>/payments')
    def add_payment(project_id: int):
        db = get_db(); project = db.execute('SELECT * FROM projects WHERE id = ?', (project_id,)).fetchone(); client = db.execute('SELECT * FROM clients WHERE id = ?', (project['client_id'],)).fetchone(); settings = get_settings(db)
        items = parse_invoice_items(request, db)
        if not items:
            flash('Agregá al menos un ítem en la factura/recibo.', 'error'); return redirect(url_for('project_detail', project_id=project_id))
        vat_percent = int(settings.get('vat_percent') or 10)
        selected_currency = (request.form.get('currency_code') or settings.get('currency_code') or 'PYG').upper()
        exchange_rate = float(request.form.get('exchange_rate') or settings.get('usd_exchange_rate') or 1)
        if exchange_rate <= 0:
            exchange_rate = 1
        subtotal_pyg = sum(i['total'] for i in items)
        if selected_currency == 'USD':
            converted_items = []
            subtotal = 0
            for item in items:
                unit_usd = round(item['unit_price'] / exchange_rate, 2)
                total_usd = round(unit_usd * item['quantity'], 2)
                converted_items.append({**item, 'unit_price': unit_usd, 'total': total_usd})
                subtotal += total_usd
            items = converted_items
            vat_included = round(calculate_included_vat(subtotal_pyg, vat_percent) / exchange_rate, 2)
            total = round(subtotal, 2)
        else:
            subtotal = subtotal_pyg
            vat_included = calculate_included_vat(subtotal, vat_percent)
            total = subtotal
            exchange_rate = 1
        doc_type = request.form['document_type'].strip().lower(); document_number = request.form.get('document_number', '').strip() or next_document_number(db, doc_type)
        payment = {
            'project_id': project_id, 'document_type': doc_type, 'document_number': document_number,
            'issue_date': request.form.get('issue_date') or date.today().isoformat(),
            'payment_condition': request.form.get('payment_condition', '').strip() or settings.get('invoice_default_condition', 'Contado'),
            'payment_method': request.form.get('payment_method', '').strip(), 'reference_number': request.form.get('reference_number', '').strip(),
            'subtotal': subtotal, 'vat_included': vat_included, 'total': total,
            'description': request.form.get('description', '').strip() or '',
            'service_items': '\n'.join([f"{i['description']} x{i['quantity']}" for i in items]), 'service_amount': subtotal,
            'extra_items': '', 'extra_amount': 0, 'domain_charge': 0,
            'status': request.form.get('status', 'Pendiente').strip(), 'observations': request.form.get('observations', '').strip(),
            'currency_code': selected_currency, 'exchange_rate': exchange_rate,
        }
        cur = db.execute('''INSERT INTO payments (project_id, document_type, document_number, issue_date, payment_condition, payment_method, reference_number, subtotal, vat_included, total, description, service_items, service_amount, extra_items, extra_amount, domain_charge, status, observations, currency_code, exchange_rate) VALUES (:project_id,:document_type,:document_number,:issue_date,:payment_condition,:payment_method,:reference_number,:subtotal,:vat_included,:total,:description,:service_items,:service_amount,:extra_items,:extra_amount,:domain_charge,:status,:observations,:currency_code,:exchange_rate)''', payment)
        payment_id = cur.lastrowid
        for item in items:
            db.execute('''INSERT INTO invoice_items (payment_id, item_type, service_id, description, quantity, unit_price, total) VALUES (?, ?, ?, ?, ?, ?, ?)''', (payment_id, item['item_type'], item['service_id'], item['description'], item['quantity'], item['unit_price'], item['total']))
        folder = Path(project['folder_path']) / '01_Documentos'; folder.mkdir(parents=True, exist_ok=True)
        filename = f"{doc_type.title()}_{document_number}_{sanitize_name(client['business_name'])}.pdf"; pdf_path = folder / filename
        payment_row = db.execute('SELECT * FROM payments WHERE id = ?', (payment_id,)).fetchone()
        company_info = get_company_info(settings)
        company_info['currency_code'] = payment_row['currency_code'] if payment_row['currency_code'] else company_info.get('currency_code', 'PYG')
        company_info['usd_exchange_rate'] = payment_row['exchange_rate'] if payment_row['exchange_rate'] else company_info.get('usd_exchange_rate', '7800')
        create_invoice_pdf(pdf_path, company_info, dict(client), dict(project), dict(payment_row), items, title=doc_type.upper())
        db.execute('UPDATE payments SET pdf_path = ? WHERE id = ?', (str(pdf_path), payment_id))
        log_activity(db, project['client_id'], project_id, f"{doc_type.title()} generada", f"{doc_type.title()} N° {document_number} creada en estado {payment['status']} por {money_display(total, selected_currency, exchange_rate)}")
        increment_document_counter(db, doc_type); db.commit(); flash(f'{doc_type.title()} registrada y PDF generado.', 'success')
        return redirect(url_for('project_detail', project_id=project_id))

    @app.get('/payments/<int:payment_id>/pdf')
    def payment_pdf(payment_id: int):
        payment = get_db().execute('SELECT * FROM payments WHERE id = ?', (payment_id,)).fetchone(); return send_file(payment['pdf_path'], as_attachment=True, download_name=Path(payment['pdf_path']).name)

    @app.post('/payments/<int:payment_id>/status')
    def payment_status_update(payment_id: int):
        db = get_db()
        payment = db.execute('SELECT * FROM payments WHERE id = ?', (payment_id,)).fetchone()
        if not payment:
            flash('No se encontró el comprobante.', 'error')
            return redirect(url_for('dashboard'))
        project = db.execute('SELECT * FROM projects WHERE id = ?', (payment['project_id'],)).fetchone()
        new_status = (request.form.get('status') or 'Pendiente').strip() or 'Pendiente'
        paid_date = request.form.get('paid_date', '').strip()
        if new_status == 'Pagado' and not paid_date:
            paid_date = date.today().isoformat()
        if new_status != 'Pagado':
            paid_date = ''
        db.execute('UPDATE payments SET status = ?, paid_date = ? WHERE id = ?', (new_status, paid_date, payment_id))
        log_activity(db, project['client_id'] if project else None, payment['project_id'], 'Estado de pago actualizado', f"Comprobante {payment['document_number']} → {new_status}{' (' + paid_date + ')' if paid_date else ''}")
        db.commit()
        flash(f'Comprobante marcado como {new_status}.', 'success')
        return redirect(url_for('project_detail', project_id=payment['project_id']))

    @app.post('/projects/<int:project_id>/versions')
    def add_version(project_id: int):
        db = get_db(); project = db.execute('SELECT * FROM projects WHERE id = ?', (project_id,)).fetchone(); file = request.files.get('html_file')
        if not file or not file.filename: flash('Seleccioná un archivo HTML.', 'error'); return redirect(url_for('project_detail', project_id=project_id))
        ext = Path(file.filename).suffix.lower();
        if ext != '.html': flash('Solo se admiten archivos .html.', 'error'); return redirect(url_for('project_detail', project_id=project_id))
        max_version = scalar(db, 'SELECT COALESCE(MAX(version_number), 0) FROM html_versions WHERE project_id = ?', (project_id,)); version_number = int(max_version) + 1
        folder_name = 'version_final' if request.form.get('is_final') == '1' else f'preview_v{version_number}'; target_folder = Path(project['folder_path']) / '03_Diseno_y_Desarrollo' / folder_name; target_folder.mkdir(parents=True, exist_ok=True)
        stored_name = ensure_unique_filename(target_folder, f"site_v{version_number}_{sanitize_name(project['code'] or 'proyecto')}.html"); target_path = target_folder / stored_name; file.save(target_path)
        if request.form.get('is_final') == '1': db.execute('UPDATE html_versions SET is_final = 0 WHERE project_id = ?', (project_id,))
        db.execute('''INSERT INTO html_versions (project_id, version_number, original_name, stored_name, relative_path, is_final, published_url, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', (project_id, version_number, file.filename, stored_name, str(target_path), 1 if request.form.get('is_final') == '1' else 0, request.form.get('published_url', '').strip(), request.form.get('notes', '').strip()))
        db.commit(); flash('Versión HTML guardada.', 'success'); return redirect(url_for('project_detail', project_id=project_id))

    @app.post('/projects/<int:project_id>/files')
    def add_file(project_id: int):
        db = get_db(); project = db.execute('SELECT * FROM projects WHERE id = ?', (project_id,)).fetchone(); file = request.files.get('project_file')
        if not file or not file.filename: flash('Seleccioná un archivo.', 'error'); return redirect(url_for('project_detail', project_id=project_id))
        ext = Path(file.filename).suffix.lower();
        if ext not in ALLOWED_UPLOADS: flash('Tipo de archivo no permitido.', 'error'); return redirect(url_for('project_detail', project_id=project_id))
        category = request.form.get('category', 'Documento').strip() or 'Documento'; purpose = request.form.get('purpose', '').strip() or category
        target_folder = Path(project['folder_path']) / category_to_subfolder(category); target_folder.mkdir(parents=True, exist_ok=True)
        safe_name = ensure_unique_filename(target_folder, secure_filename(file.filename)); target_path = target_folder / safe_name; file.save(target_path)
        db.execute('''INSERT INTO project_files (project_id, category, purpose, original_name, stored_name, relative_path, file_ext, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', (project_id, category, purpose, file.filename, safe_name, str(target_path), ext, request.form.get('notes', '').strip()))
        db.commit(); flash('Archivo agregado al proyecto.', 'success'); return redirect(url_for('project_detail', project_id=project_id))

    @app.post('/projects/<int:project_id>/renewals')
    def add_renewal(project_id: int):
        db = get_db(); project = db.execute('SELECT * FROM projects WHERE id = ?', (project_id,)).fetchone();
        db.execute('''INSERT INTO renewals (project_id, renewal_type, amount, due_date, status, notes) VALUES (?, ?, ?, ?, ?, ?)''', (project_id, request.form['renewal_type'].strip(), int(request.form.get('amount') or 0), request.form['due_date'], request.form.get('status', 'Pendiente').strip(), request.form.get('notes', '').strip()))
        db.commit(); flash('Renovación registrada.', 'success'); return redirect(url_for('project_detail', project_id=project_id))

    @app.get('/download')
    def download_file():
        path = request.args.get('path')
        name = request.args.get('name')
        if not path:
            return redirect(url_for('dashboard'))
        target = Path(path).resolve()
        allowed_roots = [DATA_ROOT.resolve()]
        if not any(target.is_relative_to(root) for root in allowed_roots):
            flash('Ruta de descarga no permitida.', 'error')
            return redirect(url_for('dashboard'))
        if not target.exists() or not target.is_file():
            flash('Archivo no encontrado.', 'error')
            return redirect(url_for('dashboard'))
        if target.suffix.lower() not in (ALLOWED_UPLOADS | {'.sqlite3'}):
            flash('Tipo de archivo no permitido.', 'error')
            return redirect(url_for('dashboard'))
        return send_file(target, as_attachment=True, download_name=name or target.name)

    def add_catalog_row(table: str):
        db = get_db(); name = request.form.get('name', '').strip()
        if not name: flash('El nombre es obligatorio.', 'error'); return
        db.execute(f'INSERT INTO {table} (name, description, sort_order, active) VALUES (?, ?, ?, 1)', (name, request.form.get('description', '').strip(), int(request.form.get('sort_order') or 99)))
        db.commit()

    def toggle_catalog_row(table: str, row_id: int):
        db = get_db(); row = db.execute(f'SELECT * FROM {table} WHERE id = ?', (row_id,)).fetchone()
        if row: db.execute(f'UPDATE {table} SET active = ? WHERE id = ?', (0 if row['active'] else 1, row_id)); db.commit()

    def delete_catalog_row(table: str, row_id: int):
        db = get_db(); db.execute(f'DELETE FROM {table} WHERE id = ?', (row_id,)); db.commit()

    return app


def scalar(db, sql: str, params: tuple = ()):
    row = db.execute(sql, params).fetchone()
    if row is None:
        return 0
    if isinstance(row, dict):
        val = next(iter(row.values()))
    else:
        val = row[0]
    return val if val is not None else 0


def current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    db = get_db()
    return db.execute(
        'SELECT id, email, role, active, created_at, last_login_at FROM users WHERE id = ? AND active = 1',
        (user_id,),
    ).fetchone()


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = getattr(g, 'current_user', None)
        if not user:
            return redirect(url_for('login'))
        if user['role'] != 'admin':
            flash('Acceso restringido a administradores.', 'error')
            return redirect(url_for('dashboard'))
        return view(*args, **kwargs)
    return wrapped


def ensure_admin_user(db) -> None:
    total = scalar(db, 'SELECT COUNT(*) FROM users')
    if total > 0:
        return
    admin_email = os.environ.get('MBARETE_ADMIN_EMAIL', 'admin@mbarete.local').strip().lower()
    admin_password = os.environ.get('MBARETE_ADMIN_PASSWORD', 'admin123')
    db.execute(
        'INSERT INTO users (email, password_hash, role, active) VALUES (?, ?, ?, 1)',
        (admin_email, generate_password_hash(admin_password), 'admin'),
    )


def parse_client_form(req) -> dict:
    return {
        'business_name': req.form['business_name'].strip(), 'category': req.form.get('category', '').strip(), 'owner_name': req.form.get('owner_name', '').strip(),
        'whatsapp': req.form.get('whatsapp', '').strip(), 'phone': req.form.get('phone', '').strip(), 'email': req.form.get('email', '').strip(),
        'address': req.form.get('address', '').strip(), 'city': req.form.get('city', '').strip(), 'ruc_ci': req.form.get('ruc_ci', '').strip(),
        'instagram': req.form.get('instagram', '').strip(), 'facebook': req.form.get('facebook', '').strip(), 'status': req.form.get('status', 'Activo').strip() or 'Activo',
    }


def active_services(db):
    return db.execute('SELECT * FROM service_catalog WHERE active = 1 ORDER BY service_kind DESC, category, name').fetchall()


def active_payment_conditions(db):
    return db.execute('SELECT * FROM payment_conditions WHERE active = 1 ORDER BY sort_order, name').fetchall()


def parse_scope_form(req, db, scope: str) -> dict:
    client_id = int(req.form['client_id'])
    main_service_raw = (req.form.get('main_service_id') or '').strip()
    custom_main_name = (req.form.get('main_service_name_override') or '').strip()
    main_service_id = int(main_service_raw) if main_service_raw.isdigit() else None
    items: list[dict] = []
    total = 0
    main_name = custom_main_name

    if main_service_id:
        row = db.execute('SELECT * FROM service_catalog WHERE id = ?', (main_service_id,)).fetchone()
        if row:
            total_line = int(row['base_price'] or 0)
            items.append({'service_id': row['id'], 'item_role': 'principal', 'service_name': row['name'], 'applied_price': total_line, 'quantity': 1, 'line_total': total_line})
            main_name = row['name']
            total += total_line
    elif main_service_raw == 'custom':
        main_name = custom_main_name or 'Proyecto personalizado'

    extra_ids = []
    seen = set()
    for v in req.form.getlist('extra_service_ids'):
        if v and v.isdigit() and v not in seen:
            seen.add(v)
            extra_ids.append(v)
    extra_rows = []
    for sid in extra_ids:
        row = db.execute('SELECT * FROM service_catalog WHERE id = ?', (int(sid),)).fetchone()
        if row:
            line_total = int(row['base_price'] or 0)
            extra_rows.append(row)
            items.append({'service_id': row['id'], 'item_role': 'extra', 'service_name': row['name'], 'applied_price': line_total, 'quantity': 1, 'line_total': line_total})
            total += line_total

    extras_text = ', '.join([r['name'] for r in extra_rows])
    payment_condition = req.form.get('payment_condition', '').strip()
    status = req.form.get('status', 'En desarrollo' if scope == 'project' else 'Borrador').strip() or ('En desarrollo' if scope == 'project' else 'Borrador')
    payload = {
        'client_id': client_id,
        'main_service_id': main_service_id,
        'title': req.form.get('title', '').strip() or main_name or 'Proyecto personalizado',
        'plan': main_name or 'Proyecto personalizado',
        'extras': extras_text,
        'total_amount': total,
        'payment_condition': payment_condition,
        'status': status,
        'notes': req.form.get('notes', '').strip(),
        'items': items,
    }
    if scope == 'project':
        payload.update({
            'start_date': req.form.get('start_date') or date.today().isoformat(), 'due_date': req.form.get('due_date') or None,
            'domain_name': req.form.get('domain_name', '').strip(), 'domain_provider': req.form.get('domain_provider', '').strip(),
            'domain_status': req.form.get('domain_status', '').strip(), 'domain_user': req.form.get('domain_user', '').strip(),
            'domain_password': req.form.get('domain_password', '').strip(), 'domain_expiry': req.form.get('domain_expiry') or None,
            'client_has_domain': 1 if req.form.get('client_has_domain') == '1' else 0,
            'hosting_provider': req.form.get('hosting_provider', '').strip(), 'hosting_status': req.form.get('hosting_status', '').strip(),
            'hosting_user': req.form.get('hosting_user', '').strip(), 'hosting_password': req.form.get('hosting_password', '').strip(),
            'hosting_expiry': req.form.get('hosting_expiry') or None, 'external_hosting': 1 if req.form.get('external_hosting') == '1' else 0,
            'technical_notes': req.form.get('technical_notes', '').strip(),
        })
    return payload


def log_activity(db, client_id, project_id, action: str, details: str = '') -> None:
    db.execute('INSERT INTO activities (client_id, project_id, action, details) VALUES (?, ?, ?, ?)', (client_id, project_id, action, details))


def save_project_items(db, project_id: int, items: list[dict]) -> None:
    for item in items:
        db.execute('''INSERT INTO project_services (project_id, service_id, item_role, service_name, applied_price, quantity, line_total) VALUES (?, ?, ?, ?, ?, ?, ?)''', (project_id, item['service_id'], item['item_role'], item['service_name'], item['applied_price'], item['quantity'], item['line_total']))


def save_budget_items(db, budget_id: int, items: list[dict]) -> None:
    for item in items:
        db.execute('''INSERT INTO budget_items (budget_id, service_id, item_role, service_name, applied_price, quantity, line_total) VALUES (?, ?, ?, ?, ?, ?, ?)''', (budget_id, item['service_id'], item['item_role'], item['service_name'], item['applied_price'], item['quantity'], item['line_total']))


def extras_text_from_items(items) -> str:
    return ', '.join([i['service_name'] for i in items if i['item_role'] == 'extra'])


def parse_invoice_items(req, db) -> list[dict]:
    types = req.form.getlist('item_type[]'); service_ids = req.form.getlist('service_id[]'); descriptions = req.form.getlist('item_description[]'); quantities = req.form.getlist('item_quantity[]'); prices = req.form.getlist('item_unit_price[]')
    items: list[dict] = []; count = max(len(descriptions), len(service_ids), len(prices), len(quantities), len(types))
    for idx in range(count):
        service_id_raw = service_ids[idx].strip() if idx < len(service_ids) else ''
        desc = descriptions[idx].strip() if idx < len(descriptions) else ''
        qty = int(quantities[idx] or 0) if idx < len(quantities) and (quantities[idx] or '').strip() else 1
        unit_price = int(prices[idx] or 0) if idx < len(prices) and (prices[idx] or '').strip() else 0
        item_type = types[idx].strip() if idx < len(types) and types[idx].strip() else 'Servicio'
        service_id = int(service_id_raw) if service_id_raw.isdigit() else None
        if service_id and not desc:
            row = db.execute('SELECT * FROM service_catalog WHERE id = ?', (service_id,)).fetchone()
            if row:
                desc = row['name']; unit_price = unit_price or int(row['base_price'] or 0)
        if not desc and unit_price == 0: continue
        qty = max(qty, 1)
        items.append({'item_type': item_type, 'service_id': service_id, 'description': desc or 'Ítem', 'quantity': qty, 'unit_price': unit_price, 'total': qty * unit_price})
    return items


def calculate_included_vat(total_amount: int, vat_percent: int = 10) -> int:
    total_amount = int(total_amount or 0)
    return 0 if total_amount <= 0 else round(total_amount * vat_percent / (100 + vat_percent))


def category_to_subfolder(category: str) -> str:
    return {
        'Documento': '01_Documentos', 'Logo cliente': '02_Materiales_del_Cliente', 'Material cliente': '02_Materiales_del_Cliente',
        'Contrato': '01_Documentos', 'Factura': '01_Documentos', 'Recibo': '01_Documentos', 'SEO': '05_SEO_y_Analytics',
        'Comunicación': '06_Comunicaciones', 'Entregable': '07_Entregables_Finales',
    }.get(category, '01_Documentos')


def ensure_unique_filename(folder: Path, filename: str) -> str:
    candidate = filename; stem = Path(filename).stem; suffix = Path(filename).suffix; i = 2
    while (folder / candidate).exists():
        candidate = f"{stem}_{i}{suffix}"; i += 1
    return candidate


def create_master_note(folder_path: Path, client, project_data: dict) -> None:
    content = f"""MBARETE DIGITAL · FICHA MAESTRA\n\nNombre del negocio: {client['business_name']}\nRubro: {client['category'] or ''}\nDueño: {client['owner_name'] or ''}\nWhatsApp: {client['whatsapp'] or ''}\nEmail: {client['email'] or ''}\nDirección: {client['address'] or ''}\nCiudad: {client['city'] or ''}\nRUC/CI: {client['ruc_ci'] or ''}\n\nServicio principal: {project_data['plan']}\nExtras: {project_data['extras']}\nMonto total: {project_data['total_amount']}\nFecha inicio: {project_data.get('start_date','')}\nFecha entrega acordada: {project_data.get('due_date','') or ''}\nDominio: {project_data.get('domain_name','')}\nHosting: {project_data.get('hosting_provider','')}\nEstado: {project_data['status']}\n"""
    (Path(folder_path) / '00_FICHA_MAESTRA.txt').write_text(content, encoding='utf-8')


def create_domain_hosting_note(folder_path: Path, client, project_data: dict) -> None:
    content = f"""DATOS DE DOMINIO Y HOSTING\n\nCliente: {client['business_name']}\nProyecto iniciado: {project_data.get('start_date','')}\n\nCliente ya tiene dominio: {'Sí' if project_data.get('client_has_domain') else 'No'}\nDominio: {project_data.get('domain_name') or '-'}\nProveedor dominio: {project_data.get('domain_provider') or '-'}\nEstado dominio: {project_data.get('domain_status') or '-'}\nUsuario dominio: {project_data.get('domain_user') or '-'}\nContraseña dominio: {project_data.get('domain_password') or '-'}\nVencimiento dominio: {project_data.get('domain_expiry') or '-'}\n\nHosting externo: {'Sí' if project_data.get('external_hosting') else 'No'}\nProveedor hosting: {project_data.get('hosting_provider') or '-'}\nEstado hosting: {project_data.get('hosting_status') or '-'}\nUsuario hosting: {project_data.get('hosting_user') or '-'}\nContraseña hosting: {project_data.get('hosting_password') or '-'}\nVencimiento hosting: {project_data.get('hosting_expiry') or '-'}\n\nNotas generales: {project_data.get('notes') or '-'}\nNotas técnicas: {project_data.get('technical_notes') or '-'}\n"""
    (Path(folder_path) / '04_Dominio_y_Hosting' / 'DATOS_DOMINIO_HOSTING.txt').write_text(content, encoding='utf-8')


def ensure_defaults() -> None:
    db = get_db()
    for key, value in DEFAULT_SETTINGS.items():
        db.execute('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO NOTHING', (key, value))
    if scalar(db, 'SELECT COUNT(*) FROM service_catalog') == 0:
        db.executemany('INSERT INTO service_catalog (name, category, service_kind, description, base_price, active) VALUES (?, ?, ?, ?, ?, 1)', DEFAULT_SERVICES)
    if scalar(db, 'SELECT COUNT(*) FROM payment_methods') == 0:
        db.executemany('INSERT INTO payment_methods (name, description, sort_order, active) VALUES (?, ?, ?, 1)', DEFAULT_PAYMENT_METHODS)
    if scalar(db, 'SELECT COUNT(*) FROM payment_conditions') == 0:
        db.executemany('INSERT INTO payment_conditions (name, description, sort_order, active) VALUES (?, ?, ?, 1)', DEFAULT_PAYMENT_CONDITIONS)
    ensure_admin_user(db)
    db.commit()


def get_settings(db=None) -> dict:
    db = db or get_db(); rows = db.execute('SELECT key, value FROM settings').fetchall(); data = {r['key']: r['value'] for r in rows}
    for k, v in DEFAULT_SETTINGS.items(): data.setdefault(k, v)
    return data


def set_setting(db, key: str, value: str) -> None:
    db.execute('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', (key, value))


def get_company_info(settings: dict) -> dict:
    return {'name': settings.get('agency_name','Mbarete Digital'), 'subtitle': settings.get('agency_subtitle','Agencia de Diseño Web'), 'location': settings.get('agency_location','Asunción, Paraguay'), 'ruc': settings.get('agency_ruc',''), 'address': settings.get('agency_address',''), 'phone': settings.get('agency_phone',''), 'email': settings.get('agency_email',''), 'website': settings.get('agency_website',''), 'logo_path': settings.get('logo_path',''), 'show_logo_on_invoice': settings.get('show_logo_on_invoice','1'), 'footer_note': settings.get('invoice_default_notes',''), 'currency_code': settings.get('currency_code','PYG'), 'usd_exchange_rate': settings.get('usd_exchange_rate','7800')}


def get_app_meta(db) -> dict:
    rows = db.execute('SELECT key, value FROM app_meta').fetchall(); meta = {r['key']: r['value'] for r in rows}; meta.setdefault('app_version', APP_VERSION); meta.setdefault('schema_version', SCHEMA_VERSION); return meta


def next_document_number(db, doc_type: str) -> str:
    settings = get_settings(db); key = 'next_invoice_number' if doc_type == 'factura' else 'next_receipt_number'; return f"{int(settings.get(key) or 1):03d}"


def increment_document_counter(db, doc_type: str) -> None:
    settings = get_settings(db); key = 'next_invoice_number' if doc_type == 'factura' else 'next_receipt_number'; set_setting(db, key, str(int(settings.get(key) or 1) + 1))


def traffic_status_for_project(project) -> str:
    if (project['status'] or '') in {'Entregado', 'Activo'}: return 'green'
    due = project['due_date']
    if not due: return 'green'
    days = (datetime.strptime(due, '%Y-%m-%d').date() - date.today()).days
    if days < 0: return 'red'
    if days <= 3: return 'yellow'
    return 'green'


def traffic_status_for_payment(payment) -> str:
    status = (payment['status'] or '').lower()
    if status == 'pagado':
        return 'green'
    if status == 'vencido':
        return 'red'
    issue = payment['issue_date']
    try:
        days = (date.today() - datetime.strptime(issue, '%Y-%m-%d').date()).days
    except Exception:
        days = 0
    if days >= 7:
        return 'red'
    return 'yellow'


def traffic_status_for_renewal(renewal) -> str:
    try:
        days = (datetime.strptime(renewal['due_date'], '%Y-%m-%d').date() - date.today()).days
    except Exception:
        return 'green'
    if renewal['status'] == 'Pagado': return 'green'
    if days < 0 or days <= 7: return 'red'
    if days <= 15: return 'yellow'
    return 'green'


app = create_app()

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    open_browser = os.environ.get('MBARETE_OPEN_BROWSER', '0') == '1'
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', '8000'))

    if open_browser:
        import threading, webbrowser
        def _open_browser() -> None:
            webbrowser.open(f'http://127.0.0.1:{port}')
        if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not debug_mode:
            threading.Timer(1.0, _open_browser).start()

    app.run(host=host, port=port, debug=debug_mode)
