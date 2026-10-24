import os
import tempfile

import pytest

# Must be set before the app (and its config) is imported.
_DB = os.path.join(tempfile.mkdtemp(), 'test.db')
os.environ['TEST_DATABASE_URL'] = f'sqlite:///{_DB}'
os.environ['SECRET_KEY'] = 'test-secret-key'

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.branch import Branch  # noqa: E402
from app.models.business import Business  # noqa: E402
from app.models.user import User  # noqa: E402

PASSWORDS = {
    'admin': ('super_admin', 'Admin@123'),
    'owner1': ('owner', 'Owner@123'),
    'manager1': ('store_manager', 'Manager@123'),
    'pharmacist1': ('pharmacist', 'Pharma@123'),
    'cashier1': ('cashier', 'Cash@123'),
    'auditor1': ('auditor', 'Audit@123'),
}


@pytest.fixture(scope='session')
def app():
    app = create_app('testing')
    app.config.update(WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)
    with app.app_context():
        db.create_all()
        biz = Business(name='Test Store', legal_name='Test Store', phone='9876543210',
                       email='t@example.com', address_line1='1 Road', state='Maharashtra',
                       city='Mumbai', pincode='400001', setup_complete=True)
        db.session.add(biz)
        db.session.flush()
        branch = Branch(business_id=biz.id, name='Main', code='BR001', address_line1='1 Road',
                        phone='9876543210', is_headquarters=True, is_active=True)
        db.session.add(branch)
        db.session.flush()
        for name, (role, pwd) in PASSWORDS.items():
            u = User(branch_id=branch.id, username=name, full_name=name, email=f'{name}@example.com',
                     role=role, is_active=True)
            u.set_password(pwd)
            db.session.add(u)
        db.session.commit()
    yield app


@pytest.fixture
def login(app):
    def _login(username):
        client = app.test_client()
        resp = client.post('/auth/login', data={'username': username, 'password': PASSWORDS[username][1]})
        assert resp.status_code == 302 and 'login' not in resp.headers['Location']
        return client
    return _login
