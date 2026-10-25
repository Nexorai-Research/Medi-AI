"""User management routes (Super Admin / Owner only)."""
import re
from flask import abort, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from . import bp
from app.extensions import db
from app.models.user import User
from app.models.branch import Branch
from app.utils.decorators import role_required

ROLE_CHOICES = ['super_admin', 'owner', 'admin', 'pharmacist', 'cashier', 'store_manager',
                 'inventory_manager', 'accountant', 'auditor', 'doctor', 'viewer']


PRIVILEGED_ROLES = {'super_admin', 'owner'}


def _scoped_user_or_404(user_id):
    """Fetch a user only if they belong to the current user's business."""
    user = User.query.get_or_404(user_id)
    if user.business_id != current_user.business_id:
        abort(404)
    return user


def _password_error(password):
    if len(password) < 8:
        return 'Password must be at least 8 characters.'
    if not (re.search(r'[a-z]', password) and re.search(r'[A-Z]', password)
            and re.search(r'\d', password) and re.search(r'[^A-Za-z0-9]', password)):
        return 'Password needs upper and lower case letters, a digit and a special character.'
    return None


def _role_error(role):
    if role not in ROLE_CHOICES:
        return 'Invalid role.'
    if role in PRIVILEGED_ROLES and current_user.role not in PRIVILEGED_ROLES:
        return 'Only an owner or super admin can assign this role.'
    return None


def _branch_id_or_none(branches):
    branch_id = request.form.get('branch_id', type=int)
    return branch_id if branch_id in {b.id for b in branches} else None


@bp.route('/')
@login_required
@role_required('super_admin', 'owner', 'admin')
def index():
    users = User.query.order_by(User.full_name).all()
    users = [u for u in users if u.business_id == current_user.business_id]
    return render_template('users/index.html', title='Users', users=users)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'owner', 'admin')
def create():
    branches = Branch.query.filter_by(business_id=current_user.business_id).all()
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return render_template('users/form.html', title='Add User', user=None, branches=branches, roles=ROLE_CHOICES)
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return render_template('users/form.html', title='Add User', user=None, branches=branches, roles=ROLE_CHOICES)
        full_name = request.form.get('full_name', '').strip()
        role = request.form.get('role', 'viewer')
        password = request.form.get('password') or ''
        error = (None if username and full_name and re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email)
                 else 'Username, full name and a valid email are required.')             or _role_error(role) or _password_error(password)
        if error:
            flash(error, 'danger')
            return render_template('users/form.html', title='Add User', user=None, branches=branches, roles=ROLE_CHOICES)
        u = User(
            username=username, email=email, full_name=full_name,
            phone=request.form.get('phone', '').strip() or None, role=role,
            branch_id=_branch_id_or_none(branches), is_active=True,
            designation=request.form.get('designation', '').strip() or None,
        )
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        flash(f'User {u.username} created.', 'success')
        return redirect(url_for('users.index'))
    return render_template('users/form.html', title='Add User', user=None, branches=branches, roles=ROLE_CHOICES)


@bp.route('/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'owner', 'admin')
def edit(user_id):
    user = _scoped_user_or_404(user_id)
    branches = Branch.query.filter_by(business_id=current_user.business_id).all()
    if request.method == 'POST':
        role = request.form.get('role', user.role)
        new_password = request.form.get('password')
        error = None
        if role != user.role:
            error = _role_error(role)
            if user.id == current_user.id:
                error = 'You cannot change your own role.'
        if user.role in PRIVILEGED_ROLES and current_user.role not in PRIVILEGED_ROLES:
            error = 'Only an owner or super admin can modify this user.'
        if user.id == current_user.id and 'is_active' not in request.form:
            error = 'You cannot deactivate your own account.'
        error = error or (_password_error(new_password) if new_password else None)
        if not request.form.get('full_name', '').strip():
            error = error or 'Full name is required.'
        if error:
            flash(error, 'danger')
            return render_template('users/form.html', title='Edit User', user=user, branches=branches, roles=ROLE_CHOICES)
        user.full_name = request.form.get('full_name', '').strip()
        user.phone = request.form.get('phone', '').strip() or None
        user.role = role
        user.branch_id = _branch_id_or_none(branches)
        user.designation = request.form.get('designation', '').strip() or None
        user.is_active = 'is_active' in request.form
        if new_password:
            user.set_password(new_password)
        db.session.commit()
        flash('User updated.', 'success')
        return redirect(url_for('users.index'))
    return render_template('users/form.html', title='Edit User', user=user, branches=branches, roles=ROLE_CHOICES)


@bp.route('/<int:user_id>/deactivate', methods=['POST'])
@login_required
@role_required('super_admin', 'owner', 'admin')
def deactivate(user_id):
    user = _scoped_user_or_404(user_id)
    if user.role in PRIVILEGED_ROLES and current_user.role not in PRIVILEGED_ROLES:
        abort(403)
    if user.id == current_user.id:
        flash('You cannot deactivate your own account.', 'danger')
        return redirect(url_for('users.index'))
    user.is_active = False
    db.session.commit()
    flash(f'User {user.username} deactivated.', 'info')
    return redirect(url_for('users.index'))
