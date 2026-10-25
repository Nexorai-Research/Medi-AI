from datetime import datetime, timedelta
from app.extensions import db
from sqlalchemy import text

def demand_forecast(medicine_id, branch_id, days_ahead=30):
    sql = text("""
        SELECT COALESCE(SUM(si.quantity),0) as total_sold
        FROM sale_items si JOIN sales s ON si.sale_id=s.id
        WHERE si.medicine_id=:mid AND s.branch_id=:bid
          AND s.invoice_date >= :since AND s.status='confirmed'
    """)
    since = datetime.utcnow() - timedelta(days=90)
    total = db.session.execute(sql, {'mid': medicine_id, 'bid': branch_id, 'since': since}).scalar() or 0
    avg_daily = float(total) / 90
    predicted = round(avg_daily * days_ahead)
    return {'predicted_qty': predicted, 'avg_daily': round(avg_daily, 2), 'confidence': min(90, int(total / 5))}

def suggest_reorder(business_id, branch_id):
    from app.models.medicine import Medicine, MedicineBatch
    medicines = Medicine.query.filter_by(business_id=business_id, is_active=True, is_deleted=False).all()
    # Two grouped queries for all medicines instead of two queries per medicine.
    stock_by_med = dict(db.session.query(MedicineBatch.medicine_id, db.func.sum(MedicineBatch.quantity))
                        .filter(MedicineBatch.branch_id == branch_id, MedicineBatch.is_expired.is_(False))
                        .group_by(MedicineBatch.medicine_id).all())
    sold_by_med = dict(db.session.execute(text("""
        SELECT si.medicine_id, SUM(si.quantity)
        FROM sale_items si JOIN sales s ON si.sale_id=s.id
        WHERE s.branch_id=:bid AND s.invoice_date >= :since AND s.status='confirmed'
        GROUP BY si.medicine_id
    """), {'bid': branch_id, 'since': datetime.utcnow() - timedelta(days=90)}).all())
    suggestions = []
    for med in medicines:
        current_stock = int(stock_by_med.get(med.id) or 0)
        avg_daily = round(float(sold_by_med.get(med.id) or 0) / 90, 2)
        days_left = round(current_stock / avg_daily) if avg_daily > 0 else 999
        suggested_qty = max(0, round(avg_daily * 30) - current_stock + med.reorder_level)
        if days_left < 30 or current_stock <= med.reorder_level:
            suggestions.append({
                'medicine_id': med.id, 'medicine_name': med.name,
                'current_stock': current_stock, 'avg_daily_sales': avg_daily,
                'days_of_stock_left': days_left, 'suggested_order_qty': suggested_qty,
                'reorder_level': med.reorder_level
            })
    return sorted(suggestions, key=lambda x: x['days_of_stock_left'])

def search_by_generic_name(business_id, query):
    from app.models.medicine import Medicine, MedicineBatch
    if not query:
        return []
    meds = Medicine.query.filter(
        Medicine.business_id == business_id,
        Medicine.is_deleted == False,
        db.or_(Medicine.generic_name.ilike(f'%{query}%'), Medicine.salt_composition.ilike(f'%{query}%'), Medicine.name.ilike(f'%{query}%')),
    ).order_by(Medicine.mrp.asc()).all()
    results = []
    for m in meds:
        batches = m.batches.filter_by(is_expired=False, is_damaged=False).all()
        total_stock = sum(b.available_qty for b in batches)
        nearest_expiry = min((b.expiry_date for b in batches if b.expiry_date), default=None)
        results.append({
            'id': m.id, 'name': m.name, 'generic_name': m.generic_name,
            'salt_composition': m.salt_composition, 'manufacturer': m.manufacturer,
            'mrp': float(m.mrp or 0), 'selling_rate': float(m.selling_rate or 0),
            'stock_qty': total_stock,
            'nearest_expiry': nearest_expiry.isoformat() if nearest_expiry else None,
        })
    return results


def find_generic_substitutes(medicine_id):
    from app.models.medicine import Medicine
    med = Medicine.query.get(medicine_id)
    if not med or not med.generic_name:
        return []
    subs = Medicine.query.filter(
        Medicine.generic_name == med.generic_name,
        Medicine.id != medicine_id,
        Medicine.is_active == True,
        Medicine.is_deleted == False
    ).order_by(Medicine.mrp.asc()).all()
    return [{'id': s.id, 'name': s.name, 'generic_name': s.generic_name, 'mrp': float(s.mrp or 0), 'manufacturer': s.manufacturer} for s in subs]

def check_drug_interactions_bulk(medicine_ids):
    from app.models.drug_interaction import DrugInteraction
    from app.models.medicine import Medicine
    generics = [m.generic_name for m in Medicine.query.filter(Medicine.id.in_(medicine_ids)).all() if m.generic_name]
    results = []
    for i, g1 in enumerate(generics):
        for g2 in generics[i+1:]:
            inter = DrugInteraction.query.filter(
                db.or_(
                    db.and_(DrugInteraction.drug_a_generic == g1, DrugInteraction.drug_b_generic == g2),
                    db.and_(DrugInteraction.drug_a_generic == g2, DrugInteraction.drug_b_generic == g1)
                )
            ).first()
            if inter:
                results.append({'drug_a': g1, 'drug_b': g2, 'severity': inter.severity, 'description': inter.description})
    return results

def detect_duplicate_invoice(supplier_id, invoice_number, business_id):
    from app.models.purchase import Purchase
    return Purchase.query.filter_by(
        supplier_id=supplier_id, invoice_number=invoice_number, business_id=business_id
    ).first() is not None

def sales_forecast(business_id, branch_id, days_ahead=30):
    from app.models.sales import Sale
    since = datetime.utcnow() - timedelta(days=90)
    total = db.session.query(db.func.coalesce(db.func.sum(Sale.total_amount), 0)).filter(
        Sale.business_id == business_id, Sale.branch_id == branch_id,
        Sale.invoice_date >= since, Sale.status == 'confirmed',
    ).scalar() or 0
    avg_daily = float(total) / 90
    predicted = round(avg_daily * days_ahead, 2)
    return {'predicted_revenue': predicted, 'avg_daily_revenue': round(avg_daily, 2), 'days_ahead': days_ahead}


def predict_expiry_risk(batch_id):
    from app.models.medicine import MedicineBatch
    batch = MedicineBatch.query.get(batch_id)
    if not batch:
        return {'will_expire_before_sale': False, 'probability': 0}
    days_to_expiry = (batch.expiry_date - datetime.utcnow().date()).days
    forecast = demand_forecast(batch.medicine_id, batch.branch_id, days_to_expiry)
    will_expire = forecast['predicted_qty'] < batch.quantity
    prob = round(min(1.0, batch.quantity / max(1, forecast['predicted_qty'])) * 100) if will_expire else 0
    return {'will_expire_before_sale': will_expire, 'probability': prob, 'days_to_expiry': days_to_expiry}
