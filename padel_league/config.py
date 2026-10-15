import os
from datetime import timedelta


class Config:
    """Base config (shared defaults)."""

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TEMPLATES_AUTO_RELOAD = True

    # Database
    POSTGRES_USER = os.getenv("POSTGRES_USER", "padel_user")
    POSTGRES_PW = os.getenv("POSTGRES_PW")
    POSTGRES_DB = os.getenv("POSTGRES_DB", "padel_league")
    POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "35.205.246.86")

    SQLALCHEMY_DATABASE_URI = f"postgresql://{POSTGRES_USER}:{POSTGRES_PW}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

    # Secret key (fallback only for dev)
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-jwt-secret")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=30)
    # The site renews the access token with this one, so active players stay signed in.
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)
    JWT_TOKEN_LOCATION = ["headers", "query_string"]
    JWT_HEADER_TYPE = "Bearer"
    JWT_QUERY_STRING_NAME = "token"
    JWT_COOKIE_CSRF_PROTECT = False

    # Email
    MAIL_SERVER = "smtp.gmail.com"
    MAIL_PORT = 465
    MAIL_USE_SSL = True
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "padelleagueporto@gmail.com")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")

    # Sessions
    SESSION_PERMANENT = False
    SESSION_TYPE = "filesystem"

    LLM_API_KEY = os.getenv("LLM_API_KEY", "")


class DevConfig(Config):
    DEBUG = True
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
    # The base class builds its URI with the production host as fallback;
    # rebuild it here so development really defaults to localhost.
    SQLALCHEMY_DATABASE_URI = f"postgresql://{Config.POSTGRES_USER}:{Config.POSTGRES_PW or ''}@{POSTGRES_HOST}:{Config.POSTGRES_PORT}/{Config.POSTGRES_DB}"


class DevConfigProdDB(Config):
    DEBUG = True
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "35.205.246.86")


def _prod_secret(name, purpose):
    """A production secret: its own env var, else derived from FLASK_SECRET_KEY.

    The deploy only passes FLASK_SECRET_KEY. Before this, SECRET_KEY and
    JWT_SECRET_KEY silently fell back to the public dev defaults in production.
    """
    explicit = os.getenv(name)
    if explicit:
        return explicit
    base = os.getenv("FLASK_SECRET_KEY")
    if not base:
        return None
    import hashlib
    import hmac

    return hmac.new(base.encode(), purpose.encode(), hashlib.sha256).hexdigest()


class ProdConfig(Config):
    DEBUG = False
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "172.17.0.1")
    SECRET_KEY = _prod_secret("SECRET_KEY", "flask-session")
    JWT_SECRET_KEY = _prod_secret("JWT_SECRET_KEY", "jwt")
