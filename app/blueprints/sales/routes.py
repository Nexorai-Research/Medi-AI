from flask import render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from . import bp
from app.extensions import db
from app.models.sales import Sale, SaleItem
from app.models.medicine import Medicine, MedicineBatch
from app.models.patient import Patient
from app.models.prescription import Prescription
from app.services.billing_service import save_invoice, generate_invoice_pdf, validate_cart
from app.services.ai_service import check_drug_interactions_bulk
from app.utils.decorators import role_required
from app.models.audit_log import AuditLog
import io
from sqlalchemy.orm import joinedload, selectinload

@bp.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    q = request.args.get('q', '')
    query = (Sale.query.filter_by(business_id=current_user.business_id)
             .options(joinedload(Sale.patient), selectinload(Sale.items)))  # list shows both per row
    if q:
        query = query.filter(Sale.invoice_number.ilike(f'%{q}%'))
    sales = query.order_by(Sale.invoice_date.desc()).paginate(page=page, per_page=20)
    return render_template('sales/list.html', sales=sales, q=q)

@bp.route('/billing')
@login_required
def billing():
    patients = Patient.query.filter_by(business_id=current_user.business_id, is_active=True).order_by(Patient.full_name).all()
    return render_template('sales/billing.html', patients=patients)

@bp.route('/billing/save', methods=['POST'])
@login_required
def billing_save():
    data = request.get_json(silent=True) or {}
    items = data.get('items', [])
    if not items:
        return jsonify({'error': 'Cart is empty'}), 422

    items, error = validate_cart(items, current_user.business_id, current_user.branch_id)
    if error:
        return jsonify({'error': error}), 422

    # Schedule H gate
    for item in items:
        med = Medicine.query.get(item['medicine_id'])
        if med and med.prescription_req and not data.get('prescription_id'):
            return jsonify({'error': f'Prescription required for: {med.name}'}), 422

    # Drug interaction gate
    medicine_ids = [item['medicine_id'] for item in items]
    interactions = check_drug_interactions_bulk(medicine_ids)
    severe = [i for i in interactions if i['severity'] in ('major', 'contraindicated')]
    override_reason = (data.get('override_reason') or '').strip()
    if severe and not override_reason:
        return jsonify({'error': 'Override reason required for severe drug interaction'}), 422

    from app.models.business import Business
    business = Business.query.get(current_user.business_id)

    patient_id, rx_id = data.get('patient_id'), data.get('prescription_id')
    if patient_id and not Patient.query.filter_by(id=patient_id, business_id=current_user.business_id).first():
        return jsonify({'error': 'Patient not found'}), 422
    if rx_id and not Prescription.query.filter_by(id=rx_id, business_id=current_user.business_id).first():
        return jsonify({'error': 'Prescription not found'}), 422
    if data.get('payment_mode', 'cash') not in ('cash', 'card', 'upi', 'credit', 'wallet'):
        return jsonify({'error': 'Invalid payment mode'}), 422
    try:
        paid_amount = max(float(data.get('paid_amount') or 0), 0)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid paid amount'}), 422

    try:
        sale = save_invoice(
            sale_data={
                'business_id': current_user.business_id,
                'branch_id': current_user.branch_id,
                'patient_id': data.get('patient_id'),
                'prescription_id': data.get('prescription_id'),
                'paid_amount': paid_amount,
                'payment_mode': data.get('payment_mode', 'cash'),
                'discount_amount': data.get('discount_amount', 0),
                'business_gstin': business.gstin if business else '',
                'customer_gstin': data.get('customer_gstin', ''),
            },
            items_data=items,
            user_id=current_user.id
        )
        if severe:
            sale.interaction_override_by = current_user.id
            sale.interaction_override_reason = override_reason
            db.session.commit()
            AuditLog.log(
                action='drug_interaction_override', module='sales',
                description=f'Overrode severe drug interaction on invoice {sale.invoice_number}: {override_reason}',
                record_type='sale', record_id=sale.id, severity='critical',
                user_id=current_user.id, ip_address=request.remote_addr,
            )
            db.session.commit()
        return jsonify({'invoice_number': sale.invoice_number, 'sale_id': sale.id, 'pdf_url': url_for('sales.invoice_pdf', sale_id=sale.id)})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@bp.route('/<int:sale_id>/invoice')
@login_required
def invoice(sale_id):
    sale = Sale.query.filter_by(id=sale_id, business_id=current_user.business_id).first_or_404()
    return render_template('sales/invoice.html', sale=sale)

@bp.route('/<int:sale_id>/invoice.pdf')
@login_required
def invoice_pdf(sale_id):
    sale = Sale.query.filter_by(id=sale_id, business_id=current_user.business_id).first_or_404()
    pdf = generate_invoice_pdf(sale_id)
    if pdf:
        return send_file(io.BytesIO(pdf), mimetype='application/pdf', download_name=f'invoice-{sale.invoice_number}.pdf')
    return redirect(url_for('sales.invoice', sale_id=sale_id))

@bp.route('/api/medicine-search')
@login_required
def medicine_search():
    q = request.args.get('q', '')
    branch_id = request.args.get('branch_id', current_user.branch_id)
    if not q or len(q) < 2:
        return jsonify([])
    meds = Medicine.query.filter(
        Medicine.business_id == current_user.business_id,
        Medicine.is_active == True,
        Medicine.is_deleted == False,
        db.or_(Medicine.name.ilike(f'%{q}%'), Medicine.generic_name.ilike(f'%{q}%'), Medicine.barcode == q)
    ).limit(10).all()
    result = []
    for m in meds:
        batches = MedicineBatch.query.filter(
            MedicineBatch.medicine_id == m.id,
            MedicineBatch.branch_id == branch_id,
            MedicineBatch.quantity > 0,
            MedicineBatch.is_expired == False,
            MedicineBatch.is_damaged == False
        ).order_by(MedicineBatch.expiry_date.asc()).all()
        result.append({
            'id': m.id, 'name': m.name, 'generic_name': m.generic_name,
            'schedule_type': m.schedule_type, 'prescription_req': m.prescription_req,
            'gst_rate': float(m.gst_rate or 0),
            'batches': [{'id': b.id, 'batch_number': b.batch_number,
                         'expiry_date': b.expiry_date.strftime('%d-%m-%Y'),
                         'available_qty': b.quantity - b.reserved_qty,
                         'selling_rate': float(b.selling_rate or m.selling_rate or 0),
                         'mrp': float(b.mrp or m.mrp or 0)} for b in batches]
        })
    return jsonify(result)

@bp.route('/api/check-interaction', methods=['POST'])
@login_required
def check_interaction():
    medicine_ids = request.get_json().get('medicine_ids', [])
    interactions = check_drug_interactions_bulk(medicine_ids)
    return jsonify(interactions)
