"""Returns routes: sales returns and purchase returns."""
from flask import render_template, request, redirect, url_for, flash
from sqlalchemy import func
from flask_login import login_required, current_user
from . import bp
from app.extensions import db
from app.models.sales import Sale, SaleItem, SalesReturn, SalesReturnItem
from app.models.purchase_return import PurchaseReturn
from app.models.sequence import Sequence


@bp.route('/')
@login_required
def index():
    bid = current_user.business_id
    sales_returns = SalesReturn.query.filter_by(business_id=bid).order_by(SalesReturn.return_date.desc()).limit(50).all()
    purchase_returns = PurchaseReturn.query.filter_by(business_id=bid).order_by(PurchaseReturn.return_date.desc()).limit(50).all()
    return render_template('returns/index.html', title='Returns', sales_returns=sales_returns, purchase_returns=purchase_returns)


@bp.route('/sales/new', methods=['GET', 'POST'])
@login_required
def sales_return_new():
    bid = current_user.business_id
    invoice_no = request.args.get('invoice', '').strip()
    sale = None
    if invoice_no:
        sale = Sale.query.filter_by(business_id=bid, invoice_number=invoice_no).first()
        if not sale:
            flash(f'No invoice found matching "{invoice_no}".', 'danger')

    if request.method == 'POST':
        sale_id = request.form.get('sale_id')
        sale_item_id = request.form.get('sale_item_id')
        sale = Sale.query.filter_by(id=sale_id, business_id=bid).first_or_404()
        sale_item = SaleItem.query.filter_by(id=sale_item_id, sale_id=sale.id).first_or_404()
        qty = request.form.get('quantity', type=int)
        if qty is None:
            qty = sale_item.quantity
        reason = request.form.get('reason', '').strip()
        refund_mode = request.form.get('refund_mode', 'cash')

        already_returned = db.session.query(func.coalesce(func.sum(SalesReturnItem.quantity), 0)).filter(
            SalesReturnItem.sale_item_id == sale_item.id).scalar()
        returnable = sale_item.quantity - already_returned
        error = None
        if sale.status != 'confirmed':
            error = 'Only confirmed invoices can be returned.'
        elif refund_mode not in ('cash', 'card', 'upi', 'credit_note'):
            error = 'Invalid refund mode.'
        elif qty < 1 or qty > returnable:
            error = f'Return quantity must be between 1 and {returnable}.'
        if error:
            flash(error, 'danger')
            return redirect(url_for('returns.sales_return_new', invoice=sale.invoice_number))

        refund_amount = round((sale_item.total_amount / sale_item.quantity) * qty, 2) if sale_item.quantity else 0
        code, _ = Sequence.next_number(f'salesreturn-{bid}', prefix='SRET-', pad=5)
        sret = SalesReturn(
            business_id=bid, branch_id=sale.branch_id, return_number=code,
            original_sale_id=sale.id, patient_id=sale.patient_id, reason=reason,
            total_refund=refund_amount, refund_mode=refund_mode, processed_by=current_user.id, status='processed',
        )
        db.session.add(sret)
        db.session.flush()
        db.session.add(SalesReturnItem(
            return_id=sret.id, sale_item_id=sale_item.id, medicine_id=sale_item.medicine_id,
            batch_id=sale_item.batch_id, quantity=qty, refund_amount=refund_amount,
        ))
        from app.models.medicine import MedicineBatch
        batch = MedicineBatch.query.get(sale_item.batch_id)
        if batch and sale_item.medicine.returnable_flag:
            batch.quantity += qty
        db.session.commit()
        flash(f'Sales return {code} processed.', 'success')
        return redirect(url_for('returns.index'))

    return render_template('returns/sales_return_new.html', title='New Sales Return', sale=sale, invoice_no=invoice_no)


@bp.route('/purchase')
@login_required
def purchase_returns():
    bid = current_user.business_id
    returns = PurchaseReturn.query.filter_by(business_id=bid).order_by(PurchaseReturn.return_date.desc()).all()
    return render_template('returns/purchase_returns.html', title='Purchase Returns', returns=returns)
