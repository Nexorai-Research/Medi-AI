"""Barcode and QR code generation services for medicines."""
import os
import io
import base64
import hashlib
from datetime import datetime
from pathlib import Path

from flask import current_app


def _get_barcode_dir():
    upload_root = current_app.config.get('UPLOAD_FOLDER',
                                         os.path.join(current_app.root_path, 'static', 'uploads'))
    barcode_dir = os.path.join(upload_root, 'barcodes')
    os.makedirs(barcode_dir, exist_ok=True)
    return barcode_dir


def _get_qr_dir():
    upload_root = current_app.config.get('UPLOAD_FOLDER',
                                         os.path.join(current_app.root_path, 'static', 'uploads'))
    qr_dir = os.path.join(upload_root, 'qrcodes')
    os.makedirs(qr_dir, exist_ok=True)
    return qr_dir


def generate_barcode(medicine_id: int, medicine_code: str) -> str:
    """Generate an EAN-13 barcode PNG for the given medicine.

    EAN-13 requires exactly 12 digits (check digit auto-appended by the library).
    We derive 12 digits from the medicine_id, zero-padded.
    If medicine_id > 999999999999 we take a hash-based suffix.

    Returns the relative path from static/ (e.g. 'uploads/barcodes/MED-0001.png')
    so it can be passed directly to url_for('static', filename=...).
    """
    try:
        import barcode as pybarcode
        from barcode.writer import ImageWriter
    except ImportError:
        current_app.logger.warning('python-barcode not installed; barcode generation skipped')
        return ''

    barcode_dir = _get_barcode_dir()
    safe_code = medicine_code.replace('/', '_').replace('\\', '_')
    filename_base = safe_code  # e.g. "MED-0001"
    output_path = os.path.join(barcode_dir, filename_base)
    final_path = output_path + '.png'

    # Build a 12-digit number from medicine_id
    ean_digits = str(medicine_id).zfill(12)[:12]

    try:
        ean_class = pybarcode.get_barcode_class('ean13')
        writer = ImageWriter()
        options = {
            'module_height': 15.0,
            'module_width':  0.5,
            'quiet_zone':    2.0,
            'font_size':     8,
            'text_distance': 3.0,
            'write_text':    True,
        }
        bc = ean_class(ean_digits, writer=writer)
        bc.save(output_path, options)
    except Exception as exc:
        current_app.logger.error('Barcode generation failed for %s: %s', medicine_code, exc)
        return ''

    # Return path relative to static folder
    static_folder = current_app.static_folder
    try:
        rel = os.path.relpath(final_path, static_folder)
    except ValueError:
        rel = final_path
    return rel


def generate_qr(data: str) -> str:
    """Generate a QR code PNG for the given data string.

    Returns relative path from static/ folder.
    """
    try:
        import qrcode
        from PIL import Image
    except ImportError:
        current_app.logger.warning('qrcode/Pillow not installed; QR generation skipped')
        return ''

    qr_dir = _get_qr_dir()
    # Use a hash of the data as filename to avoid duplicates
    name_hash = hashlib.md5(data.encode()).hexdigest()[:16]
    filename = f'qr_{name_hash}.png'
    final_path = os.path.join(qr_dir, filename)

    if not os.path.exists(final_path):
        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=6,
                border=2,
            )
            qr.add_data(data)
            qr.make(fit=True)
            img = qr.make_image(fill_color='black', back_color='white')
            img.save(final_path)
        except Exception as exc:
            current_app.logger.error('QR generation failed: %s', exc)
            return ''

    static_folder = current_app.static_folder
    try:
        rel = os.path.relpath(final_path, static_folder)
    except ValueError:
        rel = final_path
    return rel


def generate_medicine_label_pdf(batch_ids: list) -> bytes:
    """Generate a PDF of medicine labels for the given MedicineBatch IDs.

    Layout: A4 page, 4 columns x 6 rows = 24 labels per page.
    Each label contains: medicine name, generic name, MRP, batch number,
    expiry date, and an embedded barcode image.

    Returns raw PDF bytes.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Image as RLImage, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus.flowables import HRFlowable

    from ..models.medicine import MedicineBatch

    batches = MedicineBatch.query.filter(MedicineBatch.id.in_(batch_ids)).all()

    buffer = io.BytesIO()
    page_w, page_h = A4

    # Label grid: 4 cols x 6 rows on A4
    margin = 10 * mm
    col_count = 4
    row_count = 6
    label_w = (page_w - 2 * margin) / col_count
    label_h = (page_h - 2 * margin) / row_count

    from reportlab.pdfgen import canvas as pdfcanvas

    c = pdfcanvas.Canvas(buffer, pagesize=A4)

    def draw_label(canvas_obj, x, y, batch):
        """Draw a single medicine label at position (x, y) — bottom-left corner."""
        med = batch.medicine
        if not med:
            return

        pad = 2 * mm
        inner_w = label_w - 2 * pad
        ly = y + pad

        # Border
        canvas_obj.setStrokeColor(colors.grey)
        canvas_obj.setLineWidth(0.5)
        canvas_obj.rect(x, y, label_w, label_h, stroke=1, fill=0)

        # Medicine name
        canvas_obj.setFont('Helvetica-Bold', 7)
        name_text = med.name[:30]
        canvas_obj.drawCentredString(x + label_w / 2, y + label_h - pad - 4 * mm, name_text)

        # Generic name
        canvas_obj.setFont('Helvetica', 6)
        generic = (med.generic_name or '')[:35]
        canvas_obj.drawCentredString(x + label_w / 2, y + label_h - pad - 7 * mm, generic)

        # MRP and Schedule
        mrp_val = float(batch.mrp) if batch.mrp else float(med.mrp)
        canvas_obj.setFont('Helvetica-Bold', 6.5)
        canvas_obj.drawCentredString(x + label_w / 2, y + label_h - pad - 10 * mm,
                                     f'MRP: Rs.{mrp_val:.2f}   Sch: {med.schedule_type}')

        # Batch & Expiry
        canvas_obj.setFont('Helvetica', 6)
        expiry_str = batch.expiry_date.strftime('%m/%Y') if batch.expiry_date else 'N/A'
        canvas_obj.drawCentredString(x + label_w / 2, y + label_h - pad - 13 * mm,
                                     f'Batch: {batch.batch_number}   Exp: {expiry_str}')

        # Barcode image
        barcode_rel = generate_barcode(med.id, med.medicine_code)
        if barcode_rel:
            static_folder = current_app.static_folder
            barcode_abs = os.path.join(static_folder, barcode_rel)
            if os.path.exists(barcode_abs):
                try:
                    bc_w = inner_w * 0.85
                    bc_h = 8 * mm
                    bc_x = x + (label_w - bc_w) / 2
                    bc_y = ly + 1 * mm
                    canvas_obj.drawImage(barcode_abs, bc_x, bc_y, width=bc_w, height=bc_h,
                                         preserveAspectRatio=True, anchor='c')
                except Exception:
                    pass

    labels_per_page = col_count * row_count
    total = len(batches)
    idx = 0

    while idx < total:
        page_batches = batches[idx: idx + labels_per_page]
        for i, batch in enumerate(page_batches):
            col = i % col_count
            row = (row_count - 1) - (i // col_count)
            lx = margin + col * label_w
            ly = margin + row * label_h
            draw_label(c, lx, ly, batch)

        c.showPage()
        idx += labels_per_page

    c.save()
    return buffer.getvalue()
