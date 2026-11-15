"""Application configuration.

All values are read from environment variables (or a local `.env` file), so
the same code can run against a local MySQL server or a hosted MySQL service.

Two ways to configure the database are supported:

1. Separate values: MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD,
   MYSQL_DATABASE.
2. One connection URL: MYSQL_URL (or DATABASE_URL when it starts with
   ``mysql://``). Example:
   ``mysql://user:password@host:3306/database?ssl-mode=REQUIRED``

When MYSQL_URL is present it takes priority over the separate values.
"""
import os
from urllib.parse import parse_qs, unquote, urlsplit

from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

_TRUE_VALUES = {'1', 'true', 'yes', 'on'}
_ON_RENDER = (
    os.environ.get('RENDER', '').strip().lower() == 'true'
    or bool(os.environ.get('RENDER_SERVICE_ID'))
)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == '':
        return default
    return raw.strip().lower() in _TRUE_VALUES


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == '':
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _mysql_url() -> str:
    raw = (os.environ.get('MYSQL_URL') or '').strip()
    if raw:
        return raw
    candidate = (os.environ.get('DATABASE_URL') or '').strip()
    if candidate.lower().startswith(('mysql://', 'mysql2://')):
        return candidate
    return ''


def _mysql_settings() -> dict:
    settings = {
        'host': (os.environ.get('MYSQL_HOST') or 'localhost').strip(),
        'port': _env_int('MYSQL_PORT', 3306),
        'user': os.environ.get('MYSQL_USER', 'root'),
        'password': os.environ.get('MYSQL_PASSWORD', ''),
        'database': (os.environ.get('MYSQL_DATABASE') or 'lost_and_found_plus').strip(),
        'ssl': _env_bool('MYSQL_SSL', False),
        'ssl_verify': _env_bool('MYSQL_SSL_VERIFY', False),
        'ssl_verify_identity': _env_bool('MYSQL_SSL_VERIFY_IDENTITY', False),
        'ssl_ca': os.environ.get('MYSQL_SSL_CA') or None,
        'ssl_cert': os.environ.get('MYSQL_SSL_CERT') or None,
        'ssl_key': os.environ.get('MYSQL_SSL_KEY') or None,
        'url': _mysql_url(),
        'connect_timeout': _env_int('MYSQL_CONNECT_TIMEOUT', 15),
        'read_timeout': _env_int('MYSQL_READ_TIMEOUT', 30),
        'write_timeout': _env_int('MYSQL_WRITE_TIMEOUT', 30),
    }

    url = settings['url']
    if not url:
        return settings

    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    if scheme not in ('mysql', 'mysql2'):
        raise ValueError(
            'MYSQL_URL/DATABASE_URL must start with mysql:// or mysql2://. '
            'The current value uses an unsupported scheme.'
        )

    if parsed.hostname:
        settings['host'] = parsed.hostname
    if parsed.port:
        settings['port'] = int(parsed.port)
    if parsed.username:
        settings['user'] = unquote(parsed.username)
    if parsed.password is not None:
        settings['password'] = unquote(parsed.password)

    database = unquote(parsed.path.lstrip('/'))
    if database:
        settings['database'] = database

    query = parse_qs(parsed.query)

    def q(name):
        values = query.get(name) or []
        return values[0].strip() if values else ''

    ssl_mode = q('ssl-mode') or q('ssl_mode')
    if ssl_mode:
        mode = ssl_mode.lower()
        if mode in ('required', 'verify_ca', 'verify_identity', 'preferred', 'true', '1'):
            settings['ssl'] = True
        elif mode in ('disabled', 'disable', 'false', '0'):
            settings['ssl'] = False
        if mode in ('verify_ca', 'verify_identity'):
            settings['ssl_verify'] = True
        if mode == 'verify_identity':
            settings['ssl_verify_identity'] = True

    if q('ssl') or q('tls'):
        settings['ssl'] = (q('ssl') or q('tls')).lower() in _TRUE_VALUES

    if q('ssl_disabled'):
        settings['ssl'] = q('ssl_disabled').lower() not in _TRUE_VALUES

    for key in ('ssl_ca', 'ssl_cert', 'ssl_key'):
        value = q(key)
        if value:
            settings[key] = value

    return settings


_MYSQL = _mysql_settings()


class Config:
    """Central configuration. All secrets come from environment variables."""

    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

    # Database
    MYSQL_URL = _MYSQL['url']
    MYSQL_HOST = _MYSQL['host']
    MYSQL_PORT = _MYSQL['port']
    MYSQL_USER = _MYSQL['user']
    MYSQL_PASSWORD = _MYSQL['password']
    MYSQL_DATABASE = _MYSQL['database']
    MYSQL_SSL = _MYSQL['ssl']
    MYSQL_SSL_VERIFY = _MYSQL['ssl_verify']
    MYSQL_SSL_VERIFY_IDENTITY = _MYSQL['ssl_verify_identity']
    MYSQL_SSL_CA = _MYSQL['ssl_ca']
    MYSQL_SSL_CERT = _MYSQL['ssl_cert']
    MYSQL_SSL_KEY = _MYSQL['ssl_key']
    MYSQL_CONNECT_TIMEOUT = _MYSQL['connect_timeout']
    MYSQL_READ_TIMEOUT = _MYSQL['read_timeout']
    MYSQL_WRITE_TIMEOUT = _MYSQL['write_timeout']

    # Create missing tables automatically on boot. Enabled by default on
    # Render so a fresh hosted database can be initialised without shell
    # access. schema.sql only uses CREATE ... IF NOT EXISTS statements.
    AUTO_INIT_DB = _env_bool('AUTO_INIT_DB', _ON_RENDER)
    TRUST_PROXY = _env_bool('TRUST_PROXY', _ON_RENDER)

    # Uploads
    UPLOAD_FOLDER = os.environ.get(
        'UPLOAD_FOLDER', os.path.join(basedir, 'uploads')
    )
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 5 * 1024 * 1024))
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

    # Session / security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8  # 8 hours

    # Matching algorithm (weights must sum to 1.0).
    # Missing values never score points: a factor is skipped when either
    # report has no value for it, and the remaining weights are re-normalised.
    MATCH_WEIGHTS = {
        'name': 0.22,           # item name / keywords
        'category': 0.18,       # same category
        'description': 0.16,    # TF-IDF cosine similarity
        'brand': 0.10,          # brand / model
        'distinctive_marks': 0.10,
        'location': 0.10,       # token overlap + campus proximity
        'color': 0.06,          # supporting evidence only
        'date': 0.08,           # lost date vs found date compatibility
    }

    # Score bands shown to users.
    MATCH_THRESHOLDS = {
        'strong': 75,
        'possible': 55,
        'low': 35,
    }

    # Matches below this score are not stored / shown.
    MATCH_MIN_SCORE = 30


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = 'https'


class TestingConfig(Config):
    TESTING = True
    DEBUG = False
    CSRF_ENABLED = False
    AUTO_INIT_DB = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig,
}
