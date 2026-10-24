import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'fallback-secret-key-change-me')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_RECORD_QUERIES = False

    # Session
    PERMANENT_SESSION_LIFETIME = timedelta(seconds=1800)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_DURATION = timedelta(days=7)
    REMEMBER_COOKIE_HTTPONLY = True

    # Upload
    UPLOAD_FOLDER = os.path.join(BASE_DIR, os.environ.get('UPLOAD_FOLDER', 'app/static/uploads'))
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))
    ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    ALLOWED_DOCUMENT_EXTENSIONS = {'pdf', 'doc', 'docx', 'xlsx', 'xls', 'csv'}

    # Mail
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() in ('true', '1', 'yes')
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'False').lower() in ('true', '1', 'yes')
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'MSMS <noreply@example.com>')

    # Twilio
    TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
    TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
    TWILIO_FROM_NUMBER = os.environ.get('TWILIO_FROM_NUMBER')
    TWILIO_WHATSAPP_FROM = os.environ.get('TWILIO_WHATSAPP_FROM', 'whatsapp:+14155238886')

    # Rate Limiting
    RATELIMIT_STORAGE_URL = os.environ.get('REDIS_URL', 'memory://')
    RATELIMIT_DEFAULT = '200 per day;50 per hour'

    # ABHA / NHA
    ABHA_CLIENT_ID = os.environ.get('ABHA_CLIENT_ID')
    ABHA_CLIENT_SECRET = os.environ.get('ABHA_CLIENT_SECRET')
    ABHA_BASE_URL = os.environ.get('ABHA_BASE_URL', 'https://healthidsbx.abdm.gov.in/api')

    # WTF
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600

    # App meta
    APP_NAME = os.environ.get('APP_NAME', 'Medical Store Management System')
    APP_VERSION = os.environ.get('APP_VERSION', '1.0.0')


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    TESTING = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DEV_DATABASE_URL',
        'mysql+pymysql://root@localhost/msms_dev'
    )
    SQLALCHEMY_ECHO = False
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = True

    # Relaxed rate limits for dev
    RATELIMIT_DEFAULT = '1000 per day;500 per hour'
    RATELIMIT_ENABLED = True


class TestingConfig(Config):
    """Testing configuration."""
    DEBUG = True
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'TEST_DATABASE_URL',
        'mysql+pymysql://root@localhost/msms_test'
    )
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    MAIL_SUPPRESS_SEND = True


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    TESTING = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'PROD_DATABASE_URL',
        'mysql+pymysql://root@localhost/msms_prod'
    )
    SQLALCHEMY_RECORD_QUERIES = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = True
    WTF_CSRF_SSL_STRICT = True

    # Tighten rate limits in production
    RATELIMIT_DEFAULT = '200 per day;50 per hour'


config_map = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}


def get_config(env_name: str = None) -> Config:
    env = env_name or os.environ.get('FLASK_ENV', 'development')
    return config_map.get(env, DevelopmentConfig)
