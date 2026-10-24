"""GST Filing routes."""
from datetime import date
from flask import render_template, request, send_file
from flask_login import login_required, current_user
from sqlalchemy import and_, extract, func
from . import bp
from app.extensions import db
from app.models.sales import Sale, SaleItem
from app.models.purchase import Purchase, PurchaseItem
from app.models.medicine import Medicine
from app.services import report_service
import io


def _current_period():
    return request.args.get('period') or date.today().strftime('%Y-%m')


def _in_period(column, period):
    """Portable 'YYYY-MM' match (date_format() is MySQL-only)."""
    year, month = period.split('-')
    return and_(extract('year', column) == int(year),
                extract('month', column) == int(month))


@bp.route('/')
@login_required
def index():
    period = _current_period()
    bid = current_user.business_id
    sales_tax = db.session.query(
        func.coalesce(func.sum(Sale.subtotal), 0),
        func.coalesce(func.sum(Sale.cgst_amount), 0),
        func.coalesce(func.sum(Sale.sgst_amount), 0),
        func.coalesce(func.sum(Sale.igst_amount), 0),
    ).filter(
        Sale.business_id == bid,
        _in_period(Sale.invoice_date, period),
        Sale.status == 'confirmed',
    ).first()
    purchase_tax = db.session.query(
        func.coalesce(func.sum(Purchase.subtotal), 0),
        func.coalesce(func.sum(Purchase.cgst_amount), 0),
        func.coalesce(func.sum(Purchase.sgst_amount), 0),
        func.coalesce(func.sum(Purchase.igst_amount), 0),
    ).filter(
        Purchase.business_id == bid,
        _in_period(Purchase.bill_date, period),
    ).first()
    output_tax = float(sales_tax[1] + sales_tax[2] + sales_tax[3])
    input_tax = float(purchase_tax[1] + purchase_tax[2] + purchase_tax[3])
    summary = {
        'taxable_sales': float(sales_tax[0]),
        'output_tax': output_tax,
        'taxable_purchase': float(purchase_tax[0]),
        'input_tax': input_tax,
        'net_liability': round(output_tax - input_tax, 2),
    }
    return render_template('gst/index.html', title='GST Filing', period=period, summary=summary)


@bp.route('/gstr1')
@login_required
def gstr1():
    period = _current_period()
    rows = report_service.gstr1_data(current_user.business_id, period)
    return render_template('gst/gstr1.html', title='GSTR-1', period=period, rows=rows)


@bp.route('/gstr3b')
@login_required
def gstr3b():
    period = _current_period()
    bid = current_user.business_id
    sales_row = db.session.query(
        func.coalesce(func.sum(Sale.subtotal), 0),
        func.coalesce(func.sum(Sale.cgst_amount), 0),
        func.coalesce(func.sum(Sale.sgst_amount), 0),
        func.coalesce(func.sum(Sale.igst_amount), 0),
    ).filter(
        Sale.business_id == bid,
        _in_period(Sale.invoice_date, period),
        Sale.status == 'confirmed',
    ).first()
    purchase_row = db.session.query(
        func.coalesce(func.sum(Purchase.subtotal), 0),
        func.coalesce(func.sum(Purchase.cgst_amount), 0),
        func.coalesce(func.sum(Purchase.sgst_amount), 0),
        func.coalesce(func.sum(Purchase.igst_amount), 0),
    ).filter(
        Purchase.business_id == bid,
        _in_period(Purchase.bill_date, period),
    ).first()
    data = {
        'taxable_value': float(sales_row[0]),
        'cgst_collected': float(sales_row[1]),
        'sgst_collected': float(sales_row[2]),
        'igst_collected': float(sales_row[3]),
        'itc_taxable_value': float(purchase_row[0]),
        'itc_cgst': float(purchase_row[1]),
        'itc_sgst': float(purchase_row[2]),
        'itc_igst': float(purchase_row[3]),
    }
    data['tax_collected'] = data['cgst_collected'] + data['sgst_collected'] + data['igst_collected']
    data['itc_total'] = data['itc_cgst'] + data['itc_sgst'] + data['itc_igst']
    data['net_payable'] = round(data['tax_collected'] - data['itc_total'], 2)
    return render_template('gst/gstr3b.html', title='GSTR-3B', period=period, data=data)


@bp.route('/hsn-summary')
@login_required
def hsn_summary():
    period = _current_period()
    bid = current_user.business_id
    rows = (
        db.session.query(
            Medicine.hsn_code,
            func.sum(SaleItem.quantity).label('qty'),
            func.sum(SaleItem.total_amount - SaleItem.cgst_amount - SaleItem.sgst_amount - SaleItem.igst_amount).label('taxable'),
            func.sum(SaleItem.cgst_amount + SaleItem.sgst_amount + SaleItem.igst_amount).label('tax'),
        )
        .join(Medicine, SaleItem.medicine_id == Medicine.id)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.business_id == bid,
            _in_period(Sale.invoice_date, period),
            Sale.status == 'confirmed',
        )
        .group_by(Medicine.hsn_code)
        .order_by(Medicine.hsn_code)
        .all()
    )
    return render_template('gst/hsn_summary.html', title='HSN Summary', period=period, rows=rows)


@bp.route('/itc')
@login_required
def itc():
    period = _current_period()
    bid = current_user.business_id
    rows = (
        db.session.query(
            Purchase.bill_number, Purchase.bill_date, Purchase.invoice_number,
            Purchase.subtotal, Purchase.cgst_amount, Purchase.sgst_amount, Purchase.igst_amount,
        )
        .filter(
            Purchase.business_id == bid,
            _in_period(Purchase.bill_date, period),
        )
        .order_by(Purchase.bill_date.desc())
        .all()
    )
    total_itc = sum(float(r.cgst_amount + r.sgst_amount + r.igst_amount) for r in rows)
    return render_template('gst/itc.html', title='Input Tax Credit', period=period, rows=rows, total_itc=total_itc)


@bp.route('/export/gstr1.xlsx')
@login_required
def export_gstr1():
    period = _current_period()
    rows = report_service.gstr1_data(current_user.business_id, period)
    headers = ['invoice_number', 'invoice_date', 'customer_gstin', 'subtotal', 'cgst_amount', 'sgst_amount', 'igst_amount', 'total_amount']
    excel = report_service.export_to_excel(rows, headers, sheet_name=f'GSTR1-{period}')
    return send_file(io.BytesIO(excel), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                      download_name=f'gstr1-{period}.xlsx', as_attachment=True)
