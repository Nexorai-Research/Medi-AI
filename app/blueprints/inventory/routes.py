"""Stock & Inventory routes."""
from datetime import datetime
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import (
    SelectField, IntegerField, TextAreaField, HiddenField, SubmitField,
    StringField, DateField, DecimalField,
)
from wtforms.validators import DataRequired, Optional, NumberRange

from . import bp
from ...extensions import db
from ...models.medicine import Medicine, MedicineCategory, MedicineBatch
from ...models.branch import Branch
from ...models.business import Business
from ...models.stock_adjustment import StockAdjustment, StockAdjustmentItem
from ...services.inventory_service import (
    check_low_stock,
    get_expiry_alerts,
    get_non_moving_stock,
    get_dead_stock,
    adjust_stock,
    get_available_stock,
)


def _get_business():
    return Business.query.first()


# ── Stock overview ─────────────────────────────────────────────────────────────

@bp.route('/')
@login_required
def index():
    return redirect(url_for('inventory.stock'))


@bp.route('/stock')
@login_required
def stock():
    business = _get_business()
    branch_id = request.args.get('branch_id', 0, type=int) or None
    category_id = request.args.get('category_id', 0, type=int) or None
    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 30

    med_query = Medicine.query.filter_by(is_deleted=False)
    if business:
        med_query = med_query.filter_by(business_id=business.id)
    if category_id:
        med_query = med_query.filter_by(category_id=category_id)
    if q:
        like = f'%{q}%'
        med_query = med_query.filter(
            db.or_(Medicine.name.ilike(like), Medicine.generic_name.ilike(like))
        )

    pagination = med_query.order_by(Medicine.name.asc()).paginate(page=page, per_page=per_page)
    medicines = pagination.items

    stock_data = []
    for med in medicines:
        if branch_id:
            qty = get_available_stock(med.id, branch_id)
        else:
            batches = MedicineBatch.query.filter_by(
                medicine_id=med.id, is_expired=False, is_damaged=False
            ).all()
            qty = sum(b.available_qty for b in batches)
        stock_data.append({
            'medicine': med,
            'qty': qty,
            'value': round(qty * float(med.purchase_rate or 0), 2),
            'is_low': qty <= med.reorder_level,
        })

    branches = Branch.query.filter_by(
        business_id=business.id if business else 0, is_active=True
    ).all() if business else []
    categories = MedicineCategory.query.filter_by(
        business_id=business.id if business else 0
    ).order_by('name').all() if business else []

    return render_template(
        'inventory/stock.html',
        title='Stock Overview',
        stock_data=stock_data,
        pagination=pagination,
        branches=branches,
        categories=categories,
        branch_id=branch_id or 0,
        category_id=category_id or 0,
        q=q,
    )


# ── Non-moving ────────────────────────────────────────────────────────────────

@bp.route('/non-moving')
@login_required
def non_moving():
    business = _get_business()
    days = request.args.get('days', 90, type=int)
    branch_id = request.args.get('branch_id', 0, type=int) or None

    if not business:
        flash('Business not set up.', 'danger')
        return redirect(url_for('inventory.stock'))

    results = get_non_moving_stock(business.id, branch_id=branch_id, days=days)

    branches = Branch.query.filter_by(business_id=business.id, is_active=True).all()
    return render_template(
        'inventory/non_moving.html',
        title='Non-Moving Stock',
        results=results,
        days=days,
        branch_id=branch_id or 0,
        branches=branches,
    )


# ── Expiry alerts ──────────────────────────────────────────────────────────────

@bp.route('/expiry-alert')
@login_required
def expiry_alert():
    business = _get_business()
    days = request.args.get('days', 30, type=int)
    branch_id = request.args.get('branch_id', 0, type=int) or None

    if not business:
        flash('Business not set up.', 'danger')
        return redirect(url_for('inventory.stock'))

    from datetime import date, timedelta
    today = date.today()

    batches = get_expiry_alerts(business.id, branch_id=branch_id, days=days)

    # Group by urgency
    urgent_7  = [b for b in batches if b.days_to_expiry() is not None and b.days_to_expiry() <= 7]
    urgent_15 = [b for b in batches if b.days_to_expiry() is not None and 7 < b.days_to_expiry() <= 15]
    urgent_30 = [b for b in batches if b.days_to_expiry() is not None and 15 < b.days_to_expiry() <= 30]

    branches = Branch.query.filter_by(business_id=business.id, is_active=True).all()
    return render_template(
        'inventory/expiry_alert.html',
        title='Expiry Alerts',
        urgent_7=urgent_7,
        urgent_15=urgent_15,
        urgent_30=urgent_30,
        days=days,
        branch_id=branch_id or 0,
        branches=branches,
        today=today,
    )


# ── Low stock ─────────────────────────────────────────────────────────────────

@bp.route('/low-stock')
@login_required
def low_stock():
    business = _get_business()
    branch_id = request.args.get('branch_id', 0, type=int) or None

    if not business:
        flash('Business not set up.', 'danger')
        return redirect(url_for('inventory.stock'))

    results = check_low_stock(business.id, branch_id=branch_id)
    branches = Branch.query.filter_by(business_id=business.id, is_active=True).all()

    return render_template(
        'inventory/low_stock.html',
        title='Low Stock Alert',
        results=results,
        branch_id=branch_id or 0,
        branches=branches,
    )


# ── Stock adjustment ───────────────────────────────────────────────────────────

class StockAdjustForm(FlaskForm):
    medicine_id  = SelectField('Medicine *', coerce=int, validators=[DataRequired()])
    batch_id     = SelectField('Batch *', coerce=int, validators=[DataRequired()])
    adj_type     = SelectField('Adjustment Type *', validators=[DataRequired()], choices=[
        ('correction',   'Stock Correction'),
        ('damage',       'Damage Write-off'),
        ('expiry',       'Expiry Write-off'),
        ('opening',      'Opening Stock'),
        ('return',       'Supplier Return'),
        ('audit',        'Audit Adjustment'),
    ])
    qty_change   = IntegerField('Quantity Change *',
                                validators=[DataRequired()],
                                description='Positive = add stock, Negative = reduce stock')
    reason       = TextAreaField('Reason *', validators=[DataRequired()])
    submit       = SubmitField('Apply Adjustment')


@bp.route('/adjust', methods=['GET', 'POST'])
@login_required
def adjust():
    business = _get_business()
    form = StockAdjustForm()

    medicines = Medicine.query.filter_by(
        is_active=True, is_deleted=False,
        business_id=business.id if business else 0
    ).order_by(Medicine.name).all() if business else []

    form.medicine_id.choices = [(0, '-- Select Medicine --')] + [
        (m.id, f'{m.medicine_code} — {m.name}') for m in medicines
    ]

    # Populate batch choices based on selected medicine
    selected_med_id = request.form.get('medicine_id', 0, type=int)
    if selected_med_id:
        batches = MedicineBatch.query.filter_by(
            medicine_id=selected_med_id, is_damaged=False
        ).order_by(MedicineBatch.expiry_date).all()
        form.batch_id.choices = [(0, '-- Select Batch --')] + [
            (b.id, f'{b.batch_number} | Exp: {b.expiry_date} | Qty: {b.quantity}')
            for b in batches
        ]
    else:
        form.batch_id.choices = [(0, '-- Select Medicine First --')]

    if form.validate_on_submit():
        if not form.medicine_id.data or not form.batch_id.data:
            flash('Please select a medicine and batch.', 'danger')
            return redirect(url_for('inventory.adjust'))

        try:
            adj = adjust_stock(
                batch_id   = form.batch_id.data,
                qty_change = form.qty_change.data,
                reason     = form.reason.data,
                user_id    = current_user.id,
                adj_type   = form.adj_type.data,
            )
            flash(f'Stock adjustment {adj.adj_number} applied successfully.', 'success')
            return redirect(url_for('inventory.stock'))
        except Exception as e:
            db.session.rollback()
            flash(f'Adjustment failed: {e}', 'danger')

    # Recent adjustments
    recent = (StockAdjustment.query
              .filter_by(business_id=business.id if business else 0)
              .order_by(StockAdjustment.created_at.desc())
              .limit(10)
              .all()) if business else []

    return render_template(
        'inventory/adjust.html',
        title='Stock Adjustment',
        form=form,
        recent=recent,
    )


# ── Stock transfer ─────────────────────────────────────────────────────────────

class StockTransferForm(FlaskForm):
    from_branch_id = SelectField('From Branch *', coerce=int, validators=[DataRequired()])
    to_branch_id   = SelectField('To Branch *', coerce=int, validators=[DataRequired()])
    medicine_id    = SelectField('Medicine *', coerce=int, validators=[DataRequired()])
    batch_id       = SelectField('Batch *', coerce=int, validators=[DataRequired()])
    qty            = IntegerField('Quantity *', validators=[DataRequired(), NumberRange(min=1)])
    notes          = TextAreaField('Notes', validators=[Optional()])
    submit         = SubmitField('Transfer Stock')


@bp.route('/transfer', methods=['GET', 'POST'])
@login_required
def transfer():
    business = _get_business()
    form = StockTransferForm()

    branches = Branch.query.filter_by(
        business_id=business.id if business else 0, is_active=True
    ).all() if business else []
    branch_choices = [(b.id, b.name) for b in branches]
    form.from_branch_id.choices = branch_choices
    form.to_branch_id.choices   = branch_choices

    medicines = Medicine.query.filter_by(
        is_active=True, is_deleted=False,
        business_id=business.id if business else 0
    ).order_by(Medicine.name).all() if business else []
    form.medicine_id.choices = [(0, '-- Select Medicine --')] + [
        (m.id, f'{m.medicine_code} — {m.name}') for m in medicines
    ]

    selected_med_id  = request.form.get('medicine_id', 0, type=int)
    selected_from_id = request.form.get('from_branch_id', 0, type=int)
    if selected_med_id and selected_from_id:
        batches = MedicineBatch.query.filter_by(
            medicine_id=selected_med_id, branch_id=selected_from_id, is_damaged=False
        ).filter(MedicineBatch.quantity > 0).order_by(MedicineBatch.expiry_date).all()
        form.batch_id.choices = [(0, '-- Select Batch --')] + [
            (b.id, f'{b.batch_number} | Exp: {b.expiry_date} | Avail: {b.available_qty}')
            for b in batches
        ]
    else:
        form.batch_id.choices = [(0, '-- Select Medicine & Branch First --')]

    if form.validate_on_submit():
        from_bid = form.from_branch_id.data
        to_bid   = form.to_branch_id.data
        if from_bid == to_bid:
            flash('Source and destination branches cannot be the same.', 'danger')
        else:
            src_batch = MedicineBatch.query.get(form.batch_id.data)
            if not src_batch or src_batch.available_qty < form.qty.data:
                flash('Insufficient stock in selected batch.', 'danger')
            else:
                from ...models.sequence import Sequence

                # Deduct from source
                src_batch.quantity -= form.qty.data
                src_batch.updated_at = datetime.utcnow()

                # Add to destination batch (or create new)
                dest_batch = MedicineBatch.query.filter_by(
                    medicine_id=src_batch.medicine_id,
                    branch_id=to_bid,
                    batch_number=src_batch.batch_number,
                ).first()
                if dest_batch:
                    dest_batch.quantity += form.qty.data
                    dest_batch.updated_at = datetime.utcnow()
                else:
                    dest_batch = MedicineBatch(
                        medicine_id  = src_batch.medicine_id,
                        branch_id    = to_bid,
                        batch_number = src_batch.batch_number,
                        mfg_date     = src_batch.mfg_date,
                        expiry_date  = src_batch.expiry_date,
                        quantity     = form.qty.data,
                        purchase_rate = src_batch.purchase_rate,
                        mrp          = src_batch.mrp,
                        selling_rate = src_batch.selling_rate,
                    )
                    db.session.add(dest_batch)

                # Create OUT adjustment record
                out_num, _ = Sequence.next_number('stock_adjustment', prefix='ADJ-', pad=6)
                out_adj = StockAdjustment(
                    business_id = business.id if business else 1,
                    branch_id   = from_bid,
                    adj_number  = out_num,
                    adj_type    = 'transfer_out',
                    reason      = f'Transfer to branch {to_bid}. {form.notes.data or ""}',
                    adjusted_by = current_user.id,
                    status      = 'approved',
                )
                db.session.add(out_adj)
                db.session.flush()
                db.session.add(StockAdjustmentItem(
                    adjustment_id = out_adj.id,
                    batch_id      = src_batch.id,
                    medicine_id   = src_batch.medicine_id,
                    qty_before    = src_batch.quantity + form.qty.data,
                    qty_change    = -form.qty.data,
                    qty_after     = src_batch.quantity,
                ))

                db.session.commit()
                flash(f'Transferred {form.qty.data} units successfully.', 'success')
                return redirect(url_for('inventory.stock'))

    return render_template(
        'inventory/transfer.html',
        title='Stock Transfer',
        form=form,
    )
