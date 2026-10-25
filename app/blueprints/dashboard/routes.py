"""Dashboard routes."""
from datetime import date, timedelta, datetime
from flask import current_app, render_template, jsonify
from flask_login import login_required, current_user
from . import bp
from ...extensions import db
from sqlalchemy import text

def _q(sql, params=None):
    try:
        return db.session.execute(text(sql), params or {}).scalar() or 0
    except Exception:
        current_app.logger.exception('Dashboard query failed')
        db.session.rollback()
        return 0


@bp.route('/')
@login_required
def index():
    today = date.today()
    bid = current_user.business_id
    month_start = today.replace(day=1)
    # Half-open datetime ranges keep invoice_date usable by its index (DATE(col) = x cannot).
    day_start = datetime.combine(today, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    fy_start = today.replace(month=4, day=1) if today.month >= 4 else today.replace(year=today.year-1, month=4, day=1)
    # Today / month / financial-year figures come from one scan of this FY's sales.
    sales_row = (0, 0, 0, 0)
    try:
        sales_row = db.session.execute(text(
            "SELECT COALESCE(SUM(CASE WHEN invoice_date>=:ds AND invoice_date<:de THEN total_amount END),0),"
            " COALESCE(SUM(CASE WHEN invoice_date>=:ds AND invoice_date<:de THEN 1 END),0),"
            " COALESCE(SUM(CASE WHEN invoice_date>=:ms THEN total_amount END),0),"
            " COALESCE(SUM(total_amount),0)"
            " FROM sales WHERE business_id=:b AND status='confirmed' AND invoice_date>=:fs"
        ), {'b': bid, 'ds': day_start, 'de': day_end, 'ms': datetime.combine(month_start, datetime.min.time()),
            'fs': datetime.combine(fy_start, datetime.min.time())}).one()
    except Exception:
        current_app.logger.exception('Dashboard sales query failed')
        db.session.rollback()
    outstanding = _q("SELECT COALESCE(SUM(total_amount-paid_amount),0) FROM sales WHERE business_id=:b AND payment_mode='credit' AND status='confirmed'", {'b': bid})
    kpis = {
        'today_sales': sales_row[0],
        'today_transactions': sales_row[1],
        'month_sales': sales_row[2],
        'fy_sales': sales_row[3],
        'low_stock_count': _q("SELECT COUNT(*) FROM (SELECT m.id FROM medicines m LEFT JOIN medicine_batches mb ON mb.medicine_id=m.id AND mb.is_expired=0 WHERE m.business_id=:b AND m.is_deleted=0 GROUP BY m.id, m.reorder_level HAVING COALESCE(SUM(mb.quantity),0) <= m.reorder_level) t", {'b': bid}),
        'expiring_soon': _q("SELECT COUNT(*) FROM medicine_batches mb JOIN medicines m ON mb.medicine_id=m.id WHERE m.business_id=:b AND mb.expiry_date<=:ed AND mb.expiry_date>=:td AND mb.quantity>0", {'b': bid, 'ed': today + timedelta(days=30), 'td': today}),
        'outstanding': outstanding,
        'unpaid_invoices': outstanding,
        # purchase orders are draft -> sent -> partial -> received, never 'pending'
        'pending_purchases': _q("SELECT COUNT(*) FROM purchase_orders WHERE business_id=:b AND status IN ('draft','sent','partial')", {'b': bid}),
        'active_patients': _q("SELECT COUNT(*) FROM patients WHERE business_id=:b AND is_active=1", {'b': bid}),
        'dead_stock_count': 0,
        'non_moving_count': 0,
    }

    # Sales trend last 30 days: one grouped query instead of one per day
    trend_start = today - timedelta(days=29)
    by_day = {}
    try:
        rows = db.session.execute(text(
            "SELECT DATE(invoice_date) AS d, COALESCE(SUM(total_amount),0) FROM sales WHERE business_id=:b AND status='confirmed' AND invoice_date>=:s AND invoice_date<:e GROUP BY DATE(invoice_date)"
        ), {'b': bid, 's': datetime.combine(trend_start, datetime.min.time()), 'e': day_end}).fetchall()
        by_day = {str(r[0])[:10]: float(r[1]) for r in rows}
    except Exception:
        current_app.logger.exception('Dashboard trend query failed')
        db.session.rollback()
    days = [trend_start + timedelta(days=i) for i in range(30)]
    labels = [d.strftime('%d %b') for d in days]
    values = [by_day.get(d.isoformat(), 0.0) for d in days]

    # Top 5 medicines
    try:
        rows = db.session.execute(text(
            "SELECT m.name, SUM(si.quantity) as qty, SUM(si.total_amount) as amt FROM sale_items si JOIN medicines m ON si.medicine_id=m.id JOIN sales s ON si.sale_id=s.id WHERE s.business_id=:b AND s.status='confirmed' AND s.invoice_date>=:ms GROUP BY m.id ORDER BY qty DESC LIMIT 5"
        ), {'b': bid, 'ms': month_start}).fetchall()
        top_medicines = [{'name': r[0], 'quantity': int(r[1]), 'amount': float(r[2])} for r in rows]
    except Exception:
        top_medicines = []

    # Recent sales
    try:
        from app.models.sales import Sale
        recent_transactions = Sale.query.filter_by(business_id=bid).order_by(Sale.invoice_date.desc()).limit(5).all()
    except Exception:
        recent_transactions = []

    return render_template('dashboard/index.html', kpis=kpis,
        sales_trend_labels=labels, sales_trend_values=values,
        top_medicines=top_medicines, recent_transactions=recent_transactions, today=today)
