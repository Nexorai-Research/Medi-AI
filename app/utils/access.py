"""App-wide role-based access control.

Enforces the MODULE_PERMISSIONS matrix from ``decorators`` for every request,
so a new route is covered by default instead of relying on each view to opt in.
"""
from flask import abort, request
from flask_login import current_user

from .decorators import MODULE_PERMISSIONS, ROLE_HIERARCHY

# blueprint name -> permission module. Blueprints not listed are open to any
# logged-in user (dashboard, notifications, auth, ...).
BLUEPRINT_MODULE = {
    'sales': 'sales',
    'returns': 'sales',
    'prescriptions': 'prescriptions',
    'eprescription': 'prescriptions',
    'patients': 'patients',
    'doctors': 'patients',
    'loyalty': 'patients',
    'medicines': 'medicines',
    'barcode': 'medicines',
    'inventory': 'inventory',
    'purchase': 'purchase',
    'suppliers': 'suppliers',
    'gst': 'gst',
    'accounting': 'accounting',
    'reports': 'reports',
    'compliance': 'reports',
    'users': 'users',
    'branches': 'users',
    'business': 'business',
    'security': 'security',
}

# Read-only roles may still view modules above their level listed here.
EXTRA_VIEW = {'auditor': {'security'}}
READ_ONLY_ROLES = {'auditor', 'viewer'}
SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}
# Blueprints where read-only roles may still POST (mark-as-read, etc.).
WRITE_OK_BLUEPRINTS = {'auth', 'notifications', 'security'}


# GET endpoints that only render an input form for a write action.
FORM_ENDPOINT_SUFFIXES = ('.create', '.adjust', '.transfer', '.upload', '.import_rx', '.sales_return_new',
                          '.orders_create')


def _action(endpoint: str) -> str:
    if request.method in SAFE_METHODS:
        return 'create' if endpoint.endswith(FORM_ENDPOINT_SUFFIXES) else 'view'
    if 'delete' in endpoint or 'remove' in endpoint:
        return 'delete'
    if 'edit' in endpoint or 'update' in endpoint:
        return 'edit'
    return 'create'


def can_view(blueprint: str) -> bool:
    """True if the current user may open ``blueprint``'s pages (used by the nav)."""
    if not current_user.is_authenticated:
        return False
    module = BLUEPRINT_MODULE.get(blueprint)
    if module is None:
        return True
    role = getattr(current_user, 'role', '')
    if module in EXTRA_VIEW.get(role, ()):
        return True
    level = ROLE_HIERARCHY.get(role, 0)
    return level >= MODULE_PERMISSIONS.get((module, 'view'), 8)


def register_access_control(app):
    @app.before_request
    def _enforce_roles():
        if not current_user.is_authenticated or not request.blueprint:
            return  # login_required on each view still handles anonymous users
        role = getattr(current_user, 'role', '')
        module = BLUEPRINT_MODULE.get(request.blueprint)

        if (role in READ_ONLY_ROLES and request.method not in SAFE_METHODS
                and request.blueprint not in WRITE_OK_BLUEPRINTS):
            abort(403)
        if (role in READ_ONLY_ROLES and request.method in SAFE_METHODS
                and (request.endpoint or '').endswith(FORM_ENDPOINT_SUFFIXES)
                and request.blueprint not in WRITE_OK_BLUEPRINTS):
            abort(403)  # read-only roles have no use for entry forms
        if module is None:
            return

        action = _action(request.endpoint or '')
        if action == 'view' and module in EXTRA_VIEW.get(role, ()):
            return
        required = MODULE_PERMISSIONS.get((module, action))
        if required is None:  # e.g. gst/accounting define no 'delete'
            required = MODULE_PERMISSIONS.get((module, 'edit'), 8)
        if ROLE_HIERARCHY.get(role, 0) < required:
            app.logger.warning('Access denied: user %s (role=%s) -> %s.%s',
                               current_user.id, role, module, action)
            abort(403)

    app.jinja_env.globals['can_view'] = can_view
