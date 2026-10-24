"""Application factory for the Medical Store Management System."""
import os
import logging
from urllib.parse import urlsplit
from flask import Flask, render_template, g
from .config import get_config
from .extensions import db, migrate, login_manager, bcrypt, mail, limiter, csrf


def _ensure_database_exists(sqlalchemy_uri: str) -> None:
    """Create the target MySQL database if it does not exist yet.

    SQLAlchemy/PyMySQL can only connect to a database that already exists,
    so on a fresh machine (empty MySQL server, no database created yet)
    every run would fail before db.create_all() ever gets a chance to run.
    This connects to the MySQL server without selecting a database, then
    issues CREATE DATABASE IF NOT EXISTS for the one in the URI.
    """
    if not sqlalchemy_uri.startswith('mysql'):
        return

    import pymysql

    parts = urlsplit(sqlalchemy_uri)
    db_name = parts.path.lstrip('/')
    if not db_name:
        return

    connection = pymysql.connect(
        host=parts.hostname or 'localhost',
        port=parts.port or 3306,
        user=parts.username or 'root',
        password=parts.password or '',
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        connection.commit()
    finally:
        connection.close()


def create_app(config_name: str = None) -> Flask:
    """Create and configure the Flask application.

    Args:
        config_name: 'development', 'production', or 'testing'.
                     Defaults to the FLASK_ENV environment variable.
    """
    app = Flask(
        __name__,
        template_folder='templates',
        static_folder='static',
    )

    # ── Configuration ──────────────────────────────────────────────────────────
    cfg = get_config(config_name)
    app.config.from_object(cfg)

    if not (app.config.get('DEBUG') or app.config.get('TESTING')) and             app.config.get('SECRET_KEY') in (None, '', 'fallback-secret-key-change-me'):
        raise RuntimeError('SECRET_KEY must be set to a strong random value outside development.')

    # Ensure upload directory exists
    os.makedirs(app.config.get('UPLOAD_FOLDER', 'app/static/uploads'), exist_ok=True)

    # ── Database auto-provisioning ───────────────────────────────────────────────
    # Creates the MySQL database itself if it doesn't exist yet, so a fresh
    # clone only needs a running MySQL server + a correct .env — no manual
    # `CREATE DATABASE` step required.
    try:
        _ensure_database_exists(app.config['SQLALCHEMY_DATABASE_URI'])
    except Exception as exc:
        logging.getLogger(__name__).warning('Could not auto-create database: %s', exc)

    # ── Extensions ─────────────────────────────────────────────────────────────
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    # ── Login manager user loader ───────────────────────────────────────────────
    from .models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # ── Auto-create all tables ──────────────────────────────────────────────────
    # Imports every model (registering it on db.metadata) then creates any
    # table that doesn't exist yet. Safe to run on every startup: create_all()
    # never touches tables that already exist, so this never drops/loses data.
    with app.app_context():
        from . import models  # noqa: F401
        db.create_all()

    # ── Blueprints ─────────────────────────────────────────────────────────────
    _register_blueprints(app)

    from .utils.access import register_access_control
    register_access_control(app)

    # ── Context processors ─────────────────────────────────────────────────────
    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        business = None
        unread_count = 0
        try:
            from .models.business import Business
            business = Business.query.first()
        except Exception:
            pass
        try:
            if current_user.is_authenticated:
                # Placeholder — replace with real notification query when model exists
                unread_count = 0
        except Exception:
            pass
        return dict(
            business=business,
            unread_count=unread_count,
            app_name=app.config.get('APP_NAME', 'MSMS'),
        )

    # ── Error handlers ──────────────────────────────────────────────────────────
    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        app.logger.exception('Internal server error: %s', e)
        return render_template('errors/500.html'), 500

    # ── Logging ────────────────────────────────────────────────────────────────
    if not app.debug:
        logging.basicConfig(level=logging.INFO)
        app.logger.setLevel(logging.INFO)

    app.logger.info('MSMS application started (env=%s)', config_name or os.environ.get('FLASK_ENV', 'development'))

    return app


def _register_blueprints(app: Flask) -> None:
    """Register all application blueprints, wrapping each in a try/except
    so that blueprints whose route files do not yet exist do not crash startup."""

    blueprint_specs = [
        ('app.blueprints.auth',           'auth',           '/auth'),
        ('app.blueprints.dashboard',      'dashboard',      '/'),
        ('app.blueprints.business',       'business',       '/business'),
        ('app.blueprints.users',          'users',          '/users'),
        ('app.blueprints.medicines',      'medicines',      '/medicines'),
        ('app.blueprints.inventory',      'inventory',      '/inventory'),
        ('app.blueprints.suppliers',      'suppliers',      '/suppliers'),
        ('app.blueprints.purchase',       'purchase',       '/purchase'),
        ('app.blueprints.sales',          'sales',          '/sales'),
        ('app.blueprints.prescriptions',  'prescriptions',  '/prescriptions'),
        ('app.blueprints.patients',       'patients',       '/patients'),
        ('app.blueprints.doctors',        'doctors',        '/doctors'),
        ('app.blueprints.gst',            'gst',            '/gst'),
        ('app.blueprints.accounting',     'accounting',     '/accounting'),
        ('app.blueprints.returns',        'returns',        '/returns'),
        ('app.blueprints.compliance',     'compliance',     '/compliance'),
        ('app.blueprints.reports',        'reports',        '/reports'),
        ('app.blueprints.notifications',  'notifications',  '/notifications'),
        ('app.blueprints.branches',       'branches',       '/branches'),
        ('app.blueprints.abha',           'abha',           '/abha'),
        ('app.blueprints.eprescription',  'eprescription',  '/eprescription'),
        ('app.blueprints.loyalty',        'loyalty',        '/loyalty'),
        ('app.blueprints.whatsapp',       'whatsapp',       '/whatsapp'),
        ('app.blueprints.barcode',        'barcode',        '/barcode'),
        ('app.blueprints.security',       'security',       '/security'),
        ('app.blueprints.ai',             'ai',             '/ai'),
    ]

    for module_path, bp_name, url_prefix in blueprint_specs:
        try:
            import importlib
            module = importlib.import_module(module_path)
            bp = getattr(module, 'bp', None)
            if bp is not None:
                app.register_blueprint(bp, url_prefix=url_prefix)
                app.logger.debug('Registered blueprint: %s at %s', bp_name, url_prefix)
            else:
                app.logger.warning('Blueprint object "bp" not found in %s', module_path)
        except ImportError as exc:
            app.logger.warning('Blueprint %s not registered (ImportError: %s)', bp_name, exc)
        except Exception as exc:
            app.logger.error('Blueprint %s failed to register: %s', bp_name, exc)

    # Ensure error template directory exists
    import os
    errors_dir = os.path.join(app.template_folder, 'errors')
    os.makedirs(errors_dir, exist_ok=True)
