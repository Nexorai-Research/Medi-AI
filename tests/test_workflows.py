"""Regression tests for billing, returns, purchase payments and user management."""
from datetime import date, timedelta

import pytest

from app.extensions import db
from app.models.medicine import Medicine, MedicineBatch
from app.models.purchase import Purchase
from app.models.sales import Sale


@pytest.fixture(scope='module')
def stock(app):
    with app.app_context():
        med = Medicine(business_id=1, medicine_code='T-1', name='Testol', schedule_type='OTC', gst_rate=12,
                       mrp=25, purchase_rate=10, selling_rate=20, is_active=True)
        db.session.add(med)
        db.session.flush()
        batch = MedicineBatch(medicine_id=med.id, branch_id=1, batch_number='T1',
                              expiry_date=date.today() + timedelta(days=300), quantity=10,
                              purchase_rate=10, mrp=25, selling_rate=20)
        expired = MedicineBatch(medicine_id=med.id, branch_id=1, batch_number='T0',
                                expiry_date=date.today() - timedelta(days=1), quantity=10,
                                purchase_rate=10, mrp=25, selling_rate=20)
        db.session.add_all([batch, expired])
        db.session.commit()
        return {'med': med.id, 'batch': batch.id, 'expired': expired.id}


def _bill(client, stock, **line):
    item = {'medicine_id': stock['med'], 'batch_id': stock['batch'], 'qty': 1,
            'selling_rate': 20, 'gst_rate': 12, **line}
    return client.post('/sales/billing/save', json={'items': [item], 'payment_mode': 'cash'})


@pytest.mark.parametrize('line', [
    {'qty': 0}, {'qty': -3}, {'qty': 11}, {'discount_pct': 150}, {'selling_rate': 0.01},
    {'selling_rate': 99}, {'batch_id': 'x'},
])
def test_billing_rejects_bad_lines(login, stock, line):
    assert _bill(login('cashier1'), stock, **line).status_code == 422


def test_billing_rejects_expired_batch(login, stock):
    assert _bill(login('cashier1'), stock, batch_id=stock['expired']).status_code == 422


def test_billing_decrements_stock_and_applies_bill_discount(app, login, stock):
    client = login('cashier1')
    resp = client.post('/sales/billing/save', json={
        'items': [{'medicine_id': stock['med'], 'batch_id': stock['batch'], 'qty': 2,
                   'selling_rate': 20, 'gst_rate': 0}],
        'discount_amount': 10, 'payment_mode': 'cash', 'paid_amount': 30})
    assert resp.status_code == 200
    with app.app_context():
        assert db.session.get(MedicineBatch, stock['batch']).quantity == 8
        sale = db.session.get(Sale, resp.get_json()['sale_id'])
        assert float(sale.total_amount) == 35  # (2 x 20) + 12% GST from the medicine - 10 discount, rounded


def test_sales_return_limited_to_sold_quantity(app, login, stock):
    client = login('cashier1')
    sale_id = _bill(client, stock).get_json()['sale_id']
    with app.app_context():
        item_id = db.session.get(Sale, sale_id).items[0].id
    def ret(qty):
        return client.post('/returns/sales/new', data={'sale_id': sale_id, 'sale_item_id': item_id,
                                                       'quantity': qty, 'refund_mode': 'cash'},
                           follow_redirects=True).get_data(as_text=True)
    assert 'Return quantity must be between' in ret(5)
    assert 'Return quantity must be between' in ret(0)
    assert 'processed' in ret(1)
    assert 'Return quantity must be between' in ret(1)


def test_purchase_payment_cannot_exceed_due(app, login):
    with app.app_context():
        p = Purchase(business_id=1, branch_id=1, bill_number='P-T1', supplier_id=1, total_amount=100,
                     due_amount=100, paid_amount=0)
        from app.models.supplier import Supplier
        db.session.add(Supplier(business_id=1, supplier_code='S-T', name='Sup'))
        db.session.flush()
        p.supplier_id = Supplier.query.filter_by(supplier_code='S-T').first().id
        db.session.add(p)
        db.session.commit()
        pid = p.id
    client = login('manager1')
    client.post(f'/purchase/{pid}/record-payment', data={'amount': '500', 'payment_mode': 'cash'})
    client.post(f'/purchase/{pid}/record-payment', data={'amount': 'NaN', 'payment_mode': 'cash'})
    client.post(f'/purchase/{pid}/record-payment', data={'amount': '40', 'payment_mode': 'cash'})
    with app.app_context():
        p = db.session.get(Purchase, pid)
        assert float(p.paid_amount) == 40 and float(p.due_amount) == 60


USER = {'username': 'wf1', 'full_name': 'Work Flow', 'email': 'wf1@example.com',
        'password': 'Strong@123', 'role': 'cashier', 'branch_id': 1}


def test_user_create_validates_password_and_role(login):
    client = login('admin')
    for bad in ({'password': '1'}, {'password': 'alllowercase1!'}, {'role': 'hacker'}):
        body = client.post('/users/create', data={**USER, **bad}).get_data(as_text=True)
        assert 'created' not in body
    assert 'User wf1 created' in client.post('/users/create', data=USER, follow_redirects=True).get_data(as_text=True)


def test_admin_cannot_grant_or_touch_privileged_roles(app, login):
    client = login('admin')
    client.post('/users/create', data={**USER, 'username': 'wf2', 'email': 'wf2@example.com', 'role': 'admin'})
    admin2 = app.test_client()
    admin2.post('/auth/login', data={'username': 'wf2', 'password': 'Strong@123'})
    body = admin2.post('/users/create', data={**USER, 'username': 'wf3', 'email': 'wf3@example.com',
                                              'role': 'super_admin'}).get_data(as_text=True)
    assert 'Only an owner or super admin' in body
    assert 'Only an owner or super admin' in admin2.post(
        '/users/1/edit', data={'full_name': 'x', 'role': 'viewer', 'is_active': 'on'}).get_data(as_text=True)


def test_read_only_and_low_roles_cannot_open_entry_forms(login):
    for path in ('/inventory/adjust', '/medicines/create', '/purchase/create', '/suppliers/create'):
        assert login('auditor1').get(path).status_code == 403, path
        assert login('cashier1').get(path).status_code == 403, path
    assert login('manager1').get('/inventory/adjust').status_code == 200


def test_patient_phone_must_be_valid_and_unique(login):
    client = login('cashier1')
    form = {'full_name': 'Dup Test', 'phone': '9123456780'}
    assert 'added' in client.post('/patients/create', data=form, follow_redirects=True).get_data(as_text=True)
    assert 'already exists' in client.post('/patients/create', data=form).get_data(as_text=True)
    assert 'valid phone' in client.post('/patients/create', data={**form, 'phone': 'abc'}).get_data(as_text=True)


def test_invoice_pdf_is_generated(app, login, stock):
    client = login('cashier1')
    sale_id = _bill(client, stock).get_json()['sale_id']
    resp = client.get(f'/sales/{sale_id}/invoice.pdf')
    assert resp.status_code == 200 and resp.data.startswith(b'%PDF')
