from datetime import datetime
from app.extensions import db
from app.models.sequence import Sequence
from app.models.sales import Sale, SaleItem
from app.models.gst import GstTransaction
from app.services.gst_service import calculate_line_gst, get_supply_type
from app.services.inventory_service import get_fefo_batches

def next_invoice_number(business_id, branch_id, year=None):
    if not year:
        year = datetime.utcnow().year
    code, _ = Sequence.next_number(f'invoice-{business_id}-{year}', prefix=f'INV-{year}-', pad=5)
    return code

def validate_cart(items, business_id, branch_id):
    """Check cart lines against the DB and return (clean_items, error).

    Prices and GST come from the batch/medicine rather than the client; a
    line may be sold below the batch selling rate but never above MRP.
    """
    from datetime import date
    from decimal import Decimal, InvalidOperation
    from app.models.medicine import Medicine, MedicineBatch
    clean, wanted = [], {}
    for raw in items:
        try:
            med_id, batch_id = int(raw['medicine_id']), int(raw['batch_id'])
            qty = int(raw['qty'])
            disc = Decimal(str(raw.get('discount_pct') or 0))
            rate = Decimal(str(raw['selling_rate'])) if raw.get('selling_rate') is not None else None
        except (KeyError, TypeError, ValueError, InvalidOperation):
            return None, 'Invalid cart item'
        if qty <= 0:
            return None, 'Quantity must be at least 1'
        if not 0 <= disc <= 100:
            return None, 'Discount must be between 0 and 100'
        med = Medicine.query.filter_by(id=med_id, business_id=business_id, is_deleted=False).first()
        batch = MedicineBatch.query.filter_by(id=batch_id, medicine_id=med_id, branch_id=branch_id).first()
        if not med or not batch:
            return None, 'Medicine or batch not found'
        if batch.is_damaged or batch.is_expired or batch.expiry_date < date.today():
            return None, f'Batch {batch.batch_number} of {med.name} is expired or damaged'
        if rate is None:
            rate = Decimal(str(batch.selling_rate))
        if rate < Decimal(str(batch.purchase_rate or 0)) or rate <= 0 or rate > Decimal(str(batch.mrp)):
            return None, f'Invalid rate for {med.name}'
        wanted[batch.id] = wanted.get(batch.id, 0) + qty
        if wanted[batch.id] > batch.available_qty:
            return None, f'Insufficient stock for {med.name} (batch {batch.batch_number})'
        clean.append({**raw, 'medicine_id': med.id, 'batch_id': batch.id, 'qty': qty,
                      'selling_rate': float(rate), 'mrp': float(batch.mrp),
                      'gst_rate': float(med.gst_rate), 'discount_pct': float(disc),
                      'batch_number': batch.batch_number})
    return clean, None

def save_invoice(sale_data, items_data, user_id):
    business_id = sale_data['business_id']
    branch_id = sale_data['branch_id']
    year = datetime.utcnow().year
    invoice_number = next_invoice_number(business_id, branch_id, year)
    supply_type = get_supply_type(
        sale_data.get('business_gstin', ''),
        sale_data.get('customer_gstin', '')
    )
    subtotal = cgst_total = sgst_total = igst_total = 0
    sale_items = []
    for item in items_data:
        g = calculate_line_gst(
            item['selling_rate'], item['qty'],
            item.get('discount_pct', 0), item['gst_rate'], supply_type
        )
        subtotal += g['taxable_value']
        cgst_total += g['cgst_amount']
        sgst_total += g['sgst_amount']
        igst_total += g['igst_amount']
        sale_items.append({**item, **g})
    grand_total = subtotal + cgst_total + sgst_total + igst_total
    bill_discount = min(max(float(sale_data.get('discount_amount') or 0), 0), grand_total)
    grand_total -= bill_discount
    round_off = round(round(grand_total) - grand_total, 2)
    grand_total = round(grand_total + round_off, 2)
    sale = Sale(
        business_id=business_id,
        branch_id=branch_id,
        invoice_number=invoice_number,
        patient_id=sale_data.get('patient_id'),
        prescription_id=sale_data.get('prescription_id'),
        cashier_id=user_id,
        subtotal=subtotal,
        discount_amount=bill_discount,
        cgst_amount=cgst_total,
        sgst_amount=sgst_total,
        igst_amount=igst_total,
        round_off=round_off,
        total_amount=grand_total,
        paid_amount=sale_data.get('paid_amount', grand_total),
        payment_mode=sale_data.get('payment_mode', 'cash'),
        status='confirmed'
    )
    db.session.add(sale)
    db.session.flush()
    from app.models.medicine import MedicineBatch
    for item in sale_items:
        batch = MedicineBatch.query.get(item['batch_id'])
        if batch:
            batch.quantity -= item['qty']
        si = SaleItem(
            sale_id=sale.id,
            medicine_id=item['medicine_id'],
            batch_id=item['batch_id'],
            quantity=item['qty'],
            mrp=item.get('mrp', item['selling_rate']),
            selling_rate=item['selling_rate'],
            discount_pct=item.get('discount_pct', 0),
            gst_rate=item['gst_rate'],
            cgst_amount=item['cgst_amount'],
            sgst_amount=item['sgst_amount'],
            igst_amount=item['igst_amount'],
            total_amount=item['total'],
        )
        db.session.add(si)
        _write_compliance(sale, si, item, business_id, branch_id, user_id)
    db.session.commit()
    if sale.patient_id:
        from app.services.loyalty_service import award_points_for_sale
        award_points_for_sale(sale)
    return sale

def _write_compliance(sale, sale_item, item, business_id, branch_id, user_id):
    from app.models.medicine import Medicine
    from app.models.compliance import ComplianceRecord
    med = Medicine.query.get(item['medicine_id'])
    if med and med.schedule_type in ('H', 'H1', 'X'):
        rec = ComplianceRecord(
            business_id=business_id,
            branch_id=branch_id,
            record_type='schedule_h' if med.schedule_type == 'H' else ('schedule_h1' if med.schedule_type == 'H1' else 'narcotic'),
            sale_id=sale.id,
            medicine_id=med.id,
            patient_id=sale.patient_id,
            prescription_id=sale.prescription_id,
            quantity_dispensed=item['qty'],
            dispensed_by=user_id,
            batch_number=item.get('batch_number', '')
        )
        db.session.add(rec)

def generate_invoice_pdf(sale_id):
    from flask import render_template, current_app
    try:
        from weasyprint import HTML
        sale = Sale.query.get(sale_id)
        html = render_template('sales/invoice.html', sale=sale)
        return HTML(string=html).write_pdf()
    except Exception:
        return _invoice_pdf_reportlab(sale_id)


def _invoice_pdf_reportlab(sale_id):
    """Plain invoice PDF for hosts where WeasyPrint's native libraries are missing."""
    import io
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        sale = Sale.query.get(sale_id)
        biz = sale.branch.business if sale.branch else None
        styles = getSampleStyleSheet()
        money = lambda v: f'Rs. {float(v or 0):.2f}'
        story = [
            Paragraph(f'<b>{biz.name if biz else ""}</b> - TAX INVOICE', styles['Title']),
            Paragraph(f'GSTIN: {biz.gstin or "-"} &nbsp; Drug Licence: {biz.drug_license_no or "-"}', styles['Normal']),
            Paragraph(f'Invoice: <b>{sale.invoice_number}</b> &nbsp; Date: {sale.invoice_date:%d-%m-%Y %H:%M}', styles['Normal']),
        ]
        if sale.patient:
            story.append(Paragraph(f'Bill to: {sale.patient.full_name} {sale.patient.phone or ""}', styles['Normal']))
        story.append(Spacer(1, 12))
        rows = [['#', 'Medicine', 'Batch', 'Qty', 'Rate', 'GST%', 'Amount']]
        for i, it in enumerate(sale.items, 1):
            rows.append([i, it.medicine.name, it.batch.batch_number if it.batch else '', it.quantity,
                         money(it.selling_rate), f'{float(it.gst_rate or 0):g}', money(it.total_amount)])
        rows += [['', '', '', '', '', 'Subtotal', money(sale.subtotal)],
                 ['', '', '', '', '', 'CGST', money(sale.cgst_amount)],
                 ['', '', '', '', '', 'SGST', money(sale.sgst_amount)]]
        if sale.discount_amount:
            rows.append(['', '', '', '', '', 'Discount', '-' + money(sale.discount_amount)])
        rows.append(['', '', '', '', '', 'Total', money(sale.total_amount)])
        table = Table(rows, repeatRows=1)
        table.setStyle(TableStyle([('GRID', (0, 0), (-1, len(sale.items)), 0.5, colors.grey),
                                   ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                                   ('FONTNAME', (5, -1), (-1, -1), 'Helvetica-Bold'),
                                   ('ALIGN', (3, 0), (-1, -1), 'RIGHT')]))
        story += [table, Spacer(1, 12), Paragraph(f'Payment mode: {str(sale.payment_mode).upper()}', styles['Normal'])]
        buf = io.BytesIO()
        SimpleDocTemplate(buf, pagesize=A4).build(story)
        return buf.getvalue()
    except Exception:
        return None
