import pytest

from app import create_app


def test_all_templates_compile(app):
    for name in app.jinja_env.list_templates(extensions=['html']):
        app.jinja_env.get_template(name)


def test_anonymous_redirected_to_login(app):
    resp = app.test_client().get('/sales/')
    assert resp.status_code == 302 and '/auth/login' in resp.headers['Location']


def test_login_page_loads(app):
    assert app.test_client().get('/auth/login').status_code == 200


@pytest.mark.parametrize('path', [
    '/', '/medicines/', '/sales/', '/gst/', '/gst/gstr1', '/gst/gstr3b', '/gst/hsn-summary',
    '/gst/itc', '/reports/', '/reports/view/monthly-sales', '/reports/view/gstr1-summary',
    '/business/edit', '/users/', '/security/',
])
def test_admin_can_open_pages(login, path):
    assert login('admin').get(path).status_code == 200


# role -> (paths that must be allowed, paths that must be forbidden)
ACCESS = {
    'cashier1': (['/sales/', '/medicines/', '/patients/'],
                 ['/gst/', '/accounting/', '/reports/', '/purchase/', '/users/', '/security/']),
    'pharmacist1': (['/sales/', '/purchase/', '/gst/', '/reports/'],
                    ['/users/', '/business/edit', '/security/']),
    'manager1': (['/purchase/', '/reports/', '/gst/'], ['/users/', '/security/']),
    'auditor1': (['/reports/', '/gst/', '/security/'], ['/business/edit', '/users/']),
}


@pytest.mark.parametrize('user', ACCESS)
def test_role_access(login, user):
    client = login(user)
    allowed, forbidden = ACCESS[user]
    for path in allowed:
        assert client.get(path).status_code == 200, (user, path)
    for path in forbidden:
        assert client.get(path).status_code == 403, (user, path)


def test_auditor_is_read_only(login):
    assert login('auditor1').post('/sales/billing/save', json={}).status_code == 403


def test_nav_hides_forbidden_links(login):
    html = login('cashier1').get('/').get_data(as_text=True)
    assert "/sales/" in html and "/gst/" not in html and "/users/" not in html


def test_production_requires_real_secret_key(monkeypatch):
    from app.config import ProductionConfig
    monkeypatch.setattr(ProductionConfig, 'SECRET_KEY', 'fallback-secret-key-change-me')
    with pytest.raises(RuntimeError):
        create_app('production')
