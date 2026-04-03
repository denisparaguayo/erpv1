from __future__ import annotations
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def _line(c: canvas.Canvas, text: str, x: int, y: int, size: int = 10, bold: bool = False) -> None:
    c.setFont('Helvetica-Bold' if bold else 'Helvetica', size)
    c.drawString(x, y, text)


def _right(c: canvas.Canvas, text: str, x: int, y: int, size: int = 10, bold: bool = False) -> None:
    c.setFont('Helvetica-Bold' if bold else 'Helvetica', size)
    c.drawRightString(x, y, text)


def _money(value, company: dict) -> str:
    amount = float(value or 0)
    currency = (company.get('currency_code') or 'PYG').upper()
    if currency == 'USD':
        rate = float(company.get('usd_exchange_rate') or 1)
        usd = amount / rate if rate else 0
        return f"USD {amount:,.2f}"
    return f"Gs. {amount:,.0f}".replace(',', '.')


def _safe_logo(company: dict) -> str:
    if str(company.get('show_logo_on_invoice', '1')) != '1':
        return ''
    logo_path = company.get('logo_path') or ''
    return logo_path if logo_path and Path(logo_path).exists() else ''


def create_invoice_pdf(output_path: str | Path, company: dict, client: dict, project: dict, payment: dict, items: list[dict], *, title: str) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(output_path), pagesize=A4)
    width, height = A4

    logo_path = _safe_logo(company)
    top = height - 34
    if logo_path:
        try:
            c.drawImage(ImageReader(str(logo_path)), (width / 2) - 34, top - 48, width=68, height=68, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
    y = top - 62 if logo_path else top - 10

    left_x = 42
    right_x = width - 42

    _line(c, company.get('name') or 'Mbarete Digital', left_x, y, 15, True)
    _right(c, title, right_x, y + 2, 21, True)
    y -= 14

    left_lines = [
        company.get('subtitle') or '',
        company.get('address') or company.get('location') or '',
        f"RUC: {company.get('ruc') or '-'}",
        f"Tel: {company.get('phone') or '-'}",
        f"Email: {company.get('email') or '-'}",
        f"Web: {company.get('website') or '-'}",
    ]
    right_lines = [
        f"N° {title.title()}: {payment.get('document_number') or '-'}",
        f"Fecha: {payment.get('issue_date') or '-'}",
        f"Condición: {payment.get('payment_condition') or '-'}",
        f"Moneda: {(company.get('currency_code') or 'PYG').upper()}",
    ]
    if (company.get('currency_code') or 'PYG').upper() == 'USD':
        rate = int(float(company.get('usd_exchange_rate') or 0))
        right_lines.append(f"Cambio: 1 USD = Gs. {rate:,.0f}".replace(',', '.'))

    y_left = y
    for line in left_lines:
        if line:
            _line(c, line, left_x, y_left, 10)
            y_left -= 12

    y_right = y
    for line in right_lines:
        _right(c, line, right_x, y_right, 10)
        y_right -= 12

    y = min(y_left, y_right) - 8
    c.line(40, y, width - 40, y)

    y -= 16
    _line(c, 'DATOS DEL CLIENTE', 40, y, 12, True)
    y -= 16

    left_client = [
        f"Nombre: {client.get('owner_name') or client.get('business_name') or '-'}",
        f"RUC / CI: {client.get('ruc_ci') or '-'}",
        f"Email: {client.get('email') or '-'}",
    ]
    right_client = [
        f"Negocio: {client.get('business_name') or '-'}",
        f"Teléfono: {client.get('whatsapp') or client.get('phone') or '-'}",
        f"Proyecto: {project.get('plan') or '-'}",
    ]
    col2_x = width / 2 + 10
    y_client_left = y
    for line in left_client:
        _line(c, line, 40, y_client_left, 10)
        y_client_left -= 12
    y_client_right = y
    for line in right_client:
        _line(c, line, col2_x, y_client_right, 10)
        y_client_right -= 12
    y = min(y_client_left, y_client_right) - 10

    _line(c, 'DETALLE DEL SERVICIO', 40, y, 12, True)
    y -= 16
    headers = [('Descripción', 40), ('Cant.', 332), ('Precio unitario', 380), ('Total', 540)]
    for text, x in headers:
        _line(c, text, x, y, 10, True)
    y -= 8
    c.line(40, y, width - 40, y)
    y -= 15

    for item in items:
        desc = f"[{item.get('item_type') or 'Ítem'}] {item.get('description') or '-'}"
        if len(desc) > 58:
            desc = desc[:55] + '...'
        _line(c, desc, 40, y, 10)
        _line(c, str(item.get('quantity') or 1), 338, y, 10)
        _line(c, _money(item.get('unit_price'), company), 380, y, 10)
        _right(c, _money(item.get('total'), company), width - 40, y, 10)
        y -= 14
        if y < 140:
            c.showPage()
            y = height - 60

    y -= 8
    c.line(340, y, width - 40, y)
    y -= 16
    _line(c, 'Subtotal:', 370, y, 10, True)
    _right(c, _money(payment.get('subtotal', 0), company), width - 40, y, 10)
    y -= 14
    _line(c, 'IVA incluido:', 370, y, 10, True)
    _right(c, _money(payment.get('vat_included', 0), company), width - 40, y, 10)
    y -= 16
    _line(c, 'TOTAL:', 370, y, 11, True)
    _right(c, _money(payment.get('total', 0), company), width - 40, y, 11, True)

    y -= 24
    _line(c, 'FORMA DE PAGO', 40, y, 11, True)
    y -= 16
    _line(c, f"Método: {payment.get('payment_method') or '-'}", 40, y, 10)
    y -= 12
    _line(c, f"N° referencia / comprobante: {payment.get('reference_number') or '-'}", 40, y, 10)
    observations = (payment.get('observations') or '').strip()
    if observations:
        y -= 12
        _line(c, f"Observaciones: {observations[:95]}", 40, y, 10)

    footer = company.get('footer_note') or ''
    if footer.strip():
        c.setFont('Helvetica', 9)
        c.drawCentredString(width / 2, 34, footer)
    c.save()
    return output_path
