"""Custom decorators for role-based access control."""
from functools import wraps
from flask import abort, flash, redirect, url_for, current_app
from flask_login import current_user


# ─── Role Hierarchy ───────────────────────────────────────────────────────────
# Higher number = more privileged.  A role can do everything below its level.
ROLE_HIERARCHY = {
    'viewer':            1,
    'doctor':            2,
    'cashier':           3,
    'store_manager':     5,
    'accountant':        4,
    'inventory_manager': 5,
    'pharmacist':        6,
    'auditor':           7,
    'admin':             7,
    'owner':             8,
    'super_admin':       8,
}

# ─── Module-level permissions ─────────────────────────────────────────────────
# Maps (module, action) -> minimum role level required.
MODULE_PERMISSIONS = {
    # Sales
    ('sales',       'view'):   1,
    ('sales',       'create'): 3,
    ('sales',       'edit'):   6,
    ('sales',       'delete'): 7,
    # Purchase
    ('purchase',    'view'):   4,
    ('purchase',    'create'): 5,
    ('purchase',    'edit'):   5,
    ('purchase',    'delete'): 7,
    # Inventory
    ('inventory',   'view'):   1,
    ('inventory',   'create'): 5,
    ('inventory',   'edit'):   5,
    ('inventory',   'delete'): 7,
    # Medicines
    ('medicines',   'view'):   1,
    ('medicines',   'create'): 6,
    ('medicines',   'edit'):   6,
    ('medicines',   'delete'): 7,
    # Patients
    ('patients',    'view'):   2,
    ('patients',    'create'): 3,
    ('patients',    'edit'):   3,
    ('patients',    'delete'): 7,
    # Prescriptions
    ('prescriptions', 'view'):   2,
    ('prescriptions', 'create'): 6,
    ('prescriptions', 'edit'):   6,
    ('prescriptions', 'delete'): 7,
    # Suppliers
    ('suppliers',   'view'):   4,
    ('suppliers',   'create'): 5,
    ('suppliers',   'edit'):   5,
    ('suppliers',   'delete'): 7,
    # GST / Accounting
    ('gst',         'view'):   4,
    ('gst',         'create'): 4,
    ('accounting',  'view'):   4,
    ('accounting',  'edit'):   4,
    # Reports
    ('reports',     'view'):   4,
    ('reports',     'export'): 4,
    # Users
    ('users',       'view'):   7,
    ('users',       'create'): 7,
    ('users',       'edit'):   7,
    ('users',       'delete'): 8,
    # Business / Settings
    ('business',    'view'):   7,
    ('business',    'edit'):   8,
    # Security
    ('security',    'view'):   8,
    ('security',    'edit'):   8,
}


def _user_role_level() -> int:
    """Return the numeric level of the currently authenticated user's role."""
    if not current_user.is_authenticated:
        return 0
    return ROLE_HIERARCHY.get(getattr(current_user, 'role', ''), 0)


def role_required(*roles):
    """Decorator: restrict a view to users who have one of the listed roles.

    Usage::

        @bp.route('/admin')
        @role_required('admin', 'super_admin')
        def admin_panel():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('auth.login'))
            if current_user.role not in roles:
                current_app.logger.warning(
                    'Access denied: user %s (role=%s) tried to access %s',
                    current_user.id, current_user.role, f.__name__
                )
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def permission_required(module: str, action: str):
    """Decorator: restrict a view based on module + action permission level.

    Usage::

        @bp.route('/medicines/new')
        @permission_required('medicines', 'create')
        def new_medicine():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('auth.login'))

            required_level = MODULE_PERMISSIONS.get((module, action), 8)
            user_level = _user_role_level()

            if user_level < required_level:
                current_app.logger.warning(
                    'Permission denied: user %s (role=%s, level=%d) needs level %d '
                    'for %s.%s',
                    current_user.id, current_user.role, user_level,
                    required_level, module, action
                )
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def min_role_level(level: int):
    """Decorator: require the user's role to have at least `level` in the hierarchy.

    Usage::

        @min_role_level(6)   # pharmacist or above
        def some_view():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('auth.login'))
            if _user_role_level() < level:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator
