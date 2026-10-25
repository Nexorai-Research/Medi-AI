"""Purchase blueprint routes."""
import os
import json
import uuid
from werkzeug.utils import secure_filename
from datetime import datetime, date
from decimal import Decimal

from flask import (
    render_template, redirect, url_for, flash,
    request, jsonify, abort, current_app,
)
from flask_login import login_required, current_user

from . import bp
from .forms import PurchaseForm, PurchaseOrderForm
from ...extensions import db
from ...models.purchase import Purchase, PurchaseItem, PurchaseOrder, PurchaseOrderItem
from ...models.supplier import Supplier
from ...models.medicine import Medicine, MedicineBatch
from ...models.sequence import Sequence


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_business_id():
    try:
        from ...models.business import Business
        biz = Business.query.first()
        return biz.id if biz else 1
    except Exception:
        return 1


def _get_branch_id():
    """Return the current branch id (first branch fallback)."""
    try:
        from ...models.branch import Branch
        branch = Branch.query.first()
        return branch.id if branch else 1
    except Exception:
        return 1


def _supplier_choices(business_id):
    suppliers = (
        Supplier.query
        .filter_by(business_id=business_id, is_deleted=False, is_active=True)
        .order_by(Supplier.name)
        .all()
    )
    return [(0, '-- Select Supplier --')] + [(s.id, f'{s.supplier_code} – {s.name}') for s in suppliers]


def _po_choices(business_id):
    pos = (
        PurchaseOrder.query
        .filter(
            PurchaseOrder.business_id == business_id,
            PurchaseOrder.status.in_(['sent', 'partial']),
        )
        .order_by(PurchaseOrder.order_date.desc())
        .all()
    )
    return [(0, '-- None --')] + [(p.id, p.po_number) for p in pos]


def _next_bill_number():
    year = datetime.utcnow().year
    code, _ = Sequence.next_number(
        key=f'purchase_{year}',
        prefix=f'BILL-{year}-',
        pad=4,
        reset_yearly=True,
    )
    return code


def _next_po_number():
    year = datetime.utcnow().year
    code, _ = Sequence.next_number(
        key=f'po_{year}',
        prefix=f'PO-{year}-',
        pad=4,
        reset_yearly=True,
    )
    return code


def _create_or_update_batch(purchase_item, branch_id):
    """Create or update a MedicineBatch from a PurchaseItem."""
    batch = MedicineBatch.query.filter_by(
        medicine_id=purchase_item.medicine_id,
        branch_id=branch_id,
        batch_number=purchase_item.batch_number,
    ).first()

    if batch:
        batch.quantity    += purchase_item.quantity + purchase_item.free_quantity
        batch.purchase_rate = purchase_item.purchase_rate
        batch.mrp           = purchase_item.mrp
        batch.updated_at    = datetime.utcnow()
    else:
        batch = MedicineBatch(
            medicine_id   = purchase_item.medicine_id,
            branch_id     = branch_id,
            batch_number  = purchase_item.batch_number,
            mfg_date      = purchase_item.mfg_date,
            expiry_date   = purchase_item.expiry_date,
            quantity      = purchase_item.quantity + purchase_item.free_quantity,
            purchase_rate = purchase_item.purchase_rate,
            mrp           = purchase_item.mrp,
        )
        db.session.add(batch)

    return batch


# ── Purchase List ─────────────────────────────────────────────────────────────

@bp.route('/')
@login_required
def index():
    business_id = _get_business_id()
    page   = request.args.get('page', 1, type=int)
    q      = request.args.get('q', '').strip()
    status = request.args.get('status', '')

    query = Purchase.query.filter_by(business_id=business_id)
    if q:
        query = query.join(Supplier).filter(
            db.or_(
                Purchase.bill_number.ilike(f'%{q}%'),
                Purchase.invoice_number.ilike(f'%{q}%'),
                Supplier.name.ilike(f'%{q}%'),
            )
        )
    if status:
        query = query.filter(Purchase.payment_status == status)

    purchases = query.order_by(Purchase.bill_date.desc()).paginate(
        page=page, per_page=25, error_out=False
    )

    return render_template(
        'purchase/list.html',
        purchases=purchases,
        q=q,
        status=status,
        title='Purchases',
    )


# ── Create Purchase ───────────────────────────────────────────────────────────

@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    business_id = _get_business_id()
    branch_id   = _get_branch_id()
    form = PurchaseForm()
    form.supplier_id.choices = _supplier_choices(business_id)
    form.po_id.choices       = _po_choices(business_id)

    if form.validate_on_submit():
        # Parse line items from hidden JSON field
        items_json = request.form.get('items_json', '[]')
        try:
            items_data = json.loads(items_json)
        except (ValueError, TypeError):
            items_data = []

        if not items_data:
            flash('Please add at least one item to the purchase.', 'danger')
            return render_template('purchase/create.html', form=form, title='New Purchase')

        bill_number = _next_bill_number()

        # Calculate totals
        subtotal        = Decimal('0.00')
        discount_amount = Decimal('0.00')
        cgst_total      = Decimal('0.00')
        sgst_total      = Decimal('0.00')

        purchase_items = []
        for it in items_data:
            try:
                med_id      = int(it.get('medicine_id', 0))
                qty         = int(it.get('quantity', 1))
                free_qty    = int(it.get('free_quantity', 0))
                rate        = Decimal(str(it.get('purchase_rate', 0)))
                mrp         = Decimal(str(it.get('mrp', 0)))
                disc_pct    = Decimal(str(it.get('discount_pct', 0)))
                gst_rate    = Decimal(str(it.get('gst_rate', 12)))
                batch_no    = str(it.get('batch_number') or '').strip()
            except (ValueError, TypeError, ArithmeticError):
                flash('Invalid number in item list.', 'danger')
                return render_template('purchase/create.html', form=form, title='New Purchase')
            expiry_str  = it.get('expiry_date', '')
            mfg_str     = it.get('mfg_date', '')

            if not med_id or not batch_no or not expiry_str:
                continue
            if (qty < 1 or free_qty < 0 or rate < 0 or mrp < 0 or not 0 <= disc_pct <= 100
                    or not 0 <= gst_rate <= 100 or not (rate.is_finite() and mrp.is_finite())):
                flash('Quantity must be positive and rates/discounts must be valid.', 'danger')
                return render_template('purchase/create.html', form=form, title='New Purchase')
            if not Medicine.query.filter_by(id=med_id, business_id=business_id, is_deleted=False).first():
                flash('Unknown medicine in item list.', 'danger')
                return render_template('purchase/create.html', form=form, title='New Purchase')

            try:
                expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d').date()
            except ValueError:
                try:
                    expiry_date = datetime.strptime(expiry_str, '%d/%m/%Y').date()
                except ValueError:
                    continue

            mfg_date = None
            if mfg_str:
                try:
                    mfg_date = datetime.strptime(mfg_str, '%Y-%m-%d').date()
                except ValueError:
                    pass

            # Line calculations
            line_base = rate * qty
            line_disc = line_base * disc_pct / 100
            taxable   = line_base - line_disc
            half_gst  = taxable * gst_rate / 100 / 2
            cgst      = half_gst.quantize(Decimal('0.01'))
            sgst      = half_gst.quantize(Decimal('0.01'))
            line_total = taxable + cgst + sgst

            subtotal        += line_base
            discount_amount += line_disc
            cgst_total      += cgst
            sgst_total      += sgst

            pi = PurchaseItem(
                medicine_id   = med_id,
                batch_number  = batch_no,
                mfg_date      = mfg_date,
                expiry_date   = expiry_date,
                quantity      = qty,
                free_quantity = free_qty,
                purchase_rate = rate,
                mrp           = mrp,
                discount_pct  = disc_pct,
                gst_rate      = gst_rate,
                cgst_amount   = cgst,
                sgst_amount   = sgst,
                igst_amount   = Decimal('0.00'),
                total_amount  = line_total,
            )
            purchase_items.append(pi)

        if not purchase_items:
            flash('No valid items found. Please check batch/expiry fields.', 'danger')
            return render_template('purchase/create.html', form=form, title='New Purchase')

        total_amount = subtotal - discount_amount + cgst_total + sgst_total
        paid_amount  = form.paid_amount.data or Decimal('0.00')
        if paid_amount < 0 or paid_amount > total_amount:
            flash(f'Paid amount must be between 0 and the bill total (Rs. {total_amount:.2f}).', 'danger')
            return render_template('purchase/create.html', form=form, title='New Purchase')
        due_amount   = total_amount - paid_amount

        payment_status = 'unpaid'
        if paid_amount >= total_amount:
            payment_status = 'paid'
        elif paid_amount > 0:
            payment_status = 'partial'

        po_id = form.po_id.data if form.po_id.data else None

        purchase = Purchase(
            business_id    = business_id,
            branch_id      = branch_id,
            bill_number    = bill_number,
            po_id          = po_id if po_id and po_id > 0 else None,
            supplier_id    = form.supplier_id.data,
            bill_date      = form.bill_date.data,
            invoice_number = form.invoice_number.data,
            invoice_date   = form.invoice_date.data,
            subtotal       = subtotal,
            discount_amount = discount_amount,
            cgst_amount    = cgst_total,
            sgst_amount    = sgst_total,
            igst_amount    = Decimal('0.00'),
            total_amount   = total_amount,
            paid_amount    = paid_amount,
            due_amount     = due_amount,
            payment_mode   = form.payment_mode.data,
            payment_status = payment_status,
            notes          = form.notes.data,
            created_by     = current_user.id,
        )

        for pi in purchase_items:
            purchase.items.append(pi)

        db.session.add(purchase)

        # Update supplier outstanding
        supplier = Supplier.query.get(form.supplier_id.data)
        if supplier:
            supplier.outstanding = (supplier.outstanding or Decimal('0.00')) + due_amount

        db.session.flush()

        # Create / update MedicineBatches
        for pi in purchase.items:
            _create_or_update_batch(pi, branch_id)

        # Handle OCR file upload
        ocr_file = form.ocr_bill.data
        if ocr_file:
            upload_dir = os.path.join(current_app.config.get('UPLOAD_FOLDER', 'app/static/uploads'), 'bills')
            os.makedirs(upload_dir, exist_ok=True)
            filename = f'{bill_number}_{secure_filename(ocr_file.filename) or "bill"}'
            filepath = os.path.join(upload_dir, filename)
            ocr_file.save(filepath)
            purchase.ocr_bill_path = filepath

        db.session.commit()
        flash(f'Purchase {bill_number} recorded successfully.', 'success')
        return redirect(url_for('purchase.detail', purchase_id=purchase.id))

    return render_template('purchase/create.html', form=form, title='New Purchase')


# ── Purchase Detail ───────────────────────────────────────────────────────────

@bp.route('/<int:purchase_id>')
@login_required
def detail(purchase_id):
    business_id = _get_business_id()
    purchase = Purchase.query.filter_by(
        id=purchase_id, business_id=business_id
    ).first_or_404()

    return render_template('purchase/detail.html', purchase=purchase, title=f'Bill – {purchase.bill_number}')


# ── Purchase Orders List ───────────────────────────────────────────────────────

@bp.route('/orders/')
@login_required
def orders_list():
    business_id = _get_business_id()
    page   = request.args.get('page', 1, type=int)
    q      = request.args.get('q', '').strip()
    status = request.args.get('status', '')

    query = PurchaseOrder.query.filter_by(business_id=business_id)
    if q:
        query = query.join(Supplier).filter(
            db.or_(
                PurchaseOrder.po_number.ilike(f'%{q}%'),
                Supplier.name.ilike(f'%{q}%'),
            )
        )
    if status:
        query = query.filter(PurchaseOrder.status == status)

    orders = query.order_by(PurchaseOrder.order_date.desc()).paginate(
        page=page, per_page=25, error_out=False
    )

    return render_template(
        'purchase/orders_list.html',
        orders=orders,
        q=q,
        status=status,
        title='Purchase Orders',
    )


# ── Create Purchase Order ─────────────────────────────────────────────────────

@bp.route('/orders/create', methods=['GET', 'POST'])
@login_required
def orders_create():
    business_id = _get_business_id()
    branch_id   = _get_branch_id()
    form = PurchaseOrderForm()
    form.supplier_id.choices = _supplier_choices(business_id)

    if form.validate_on_submit():
        items_json = request.form.get('items_json', '[]')
        try:
            items_data = json.loads(items_json)
        except (ValueError, TypeError):
            items_data = []

        po_number = _next_po_number()

        total = Decimal('0.00')
        po_items = []
        for it in items_data:
            med_id = int(it.get('medicine_id', 0))
            qty    = int(it.get('quantity', 1))
            rate   = Decimal(str(it.get('rate', 0)))
            if not med_id:
                continue
            total += rate * qty
            po_items.append(PurchaseOrderItem(
                medicine_id = med_id,
                quantity    = qty,
                rate        = rate,
            ))

        po = PurchaseOrder(
            business_id   = business_id,
            branch_id     = branch_id,
            po_number     = po_number,
            supplier_id   = form.supplier_id.data,
            order_date    = form.order_date.data,
            expected_date = form.expected_date.data,
            status        = form.status.data,
            total_amount  = total,
            notes         = form.notes.data,
            created_by    = current_user.id,
        )
        for item in po_items:
            po.items.append(item)

        db.session.add(po)
        db.session.commit()
        flash(f'Purchase Order {po_number} created.', 'success')
        return redirect(url_for('purchase.orders_list'))

    return render_template('purchase/order_create.html', form=form, title='New Purchase Order')


# ── OCR Upload (AJAX) ─────────────────────────────────────────────────────────

@bp.route('/ocr-upload', methods=['POST'])
@login_required
def ocr_upload():
    from ...services.ocr_service import extract_purchase_bill

    if 'bill_image' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded.'}), 400

    file = request.files['bill_image']
    if not file.filename:
        return jsonify({'success': False, 'error': 'Empty filename.'}), 400

    upload_dir = os.path.join(
        current_app.config.get('UPLOAD_FOLDER', 'app/static/uploads'), 'ocr_temp'
    )
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = secure_filename(file.filename)
    if not safe_name or safe_name.rsplit('.', 1)[-1].lower() not in {'png', 'jpg', 'jpeg', 'pdf', 'tif', 'tiff', 'bmp'}:
        return jsonify({'success': False, 'error': 'Unsupported file type.'}), 400
    filepath = os.path.join(upload_dir, f'{uuid.uuid4().hex[:8]}_{safe_name}')
    file.save(filepath)

    result = extract_purchase_bill(filepath)

    # Clean up temp file
    try:
        os.remove(filepath)
    except OSError:
        pass

    return jsonify(result)


# ── Pending Payments ──────────────────────────────────────────────────────────

@bp.route('/pending-payments')
@login_required
def pending_payments():
    business_id = _get_business_id()
    purchases = (
        Purchase.query
        .filter(
            Purchase.business_id == business_id,
            Purchase.payment_status.in_(['unpaid', 'partial']),
        )
        .order_by(Purchase.bill_date)
        .all()
    )
    return render_template(
        'purchase/pending_payments.html',
        purchases=purchases,
        title='Pending Payments',
    )


# ── Record Payment ────────────────────────────────────────────────────────────

@bp.route('/<int:purchase_id>/record-payment', methods=['POST'])
@login_required
def record_payment(purchase_id):
    business_id = _get_business_id()
    purchase = Purchase.query.filter_by(
        id=purchase_id, business_id=business_id
    ).first_or_404()

    amount_str  = request.form.get('amount', '0')
    mode        = request.form.get('payment_mode', 'cash')

    try:
        amount = Decimal(amount_str)
    except Exception:
        flash('Invalid payment amount.', 'danger')
        return redirect(url_for('purchase.detail', purchase_id=purchase_id))

    if not amount.is_finite() or amount <= 0:
        flash('Amount must be greater than zero.', 'danger')
        return redirect(url_for('purchase.detail', purchase_id=purchase_id))
    if amount > purchase.due_amount:
        flash(f'Payment exceeds the due amount (Rs. {purchase.due_amount}).', 'danger')
        return redirect(url_for('purchase.detail', purchase_id=purchase_id))
    if mode not in Purchase.PAYMENT_MODES:
        flash('Invalid payment mode.', 'danger')
        return redirect(url_for('purchase.detail', purchase_id=purchase_id))

    purchase.paid_amount  += amount
    purchase.due_amount    = purchase.total_amount - purchase.paid_amount
    purchase.payment_mode  = mode

    if purchase.due_amount <= 0:
        purchase.payment_status = 'paid'
        purchase.due_amount     = Decimal('0.00')
    else:
        purchase.payment_status = 'partial'

    # Update supplier outstanding
    supplier = purchase.supplier
    if supplier:
        supplier.outstanding = max(Decimal('0.00'),
                                   (supplier.outstanding or Decimal('0.00')) - amount)

    db.session.commit()
    flash(f'Payment of Rs. {amount} recorded.', 'success')
    return redirect(url_for('purchase.detail', purchase_id=purchase_id))
