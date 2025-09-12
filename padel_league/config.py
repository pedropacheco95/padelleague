import os

class Config:
    """Base config (shared defaults)."""
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TEMPLATES_AUTO_RELOAD = True

    # Database
    POSTGRES_USER = os.getenv('POSTGRES_USER', 'padel_user')
    POSTGRES_PW = os.getenv('POSTGRES_PW')
    POSTGRES_DB = os.getenv('POSTGRES_DB', 'padel_league')
    POSTGRES_PORT = os.getenv('POSTGRES_PORT', '5432')
    POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')

    SQLALCHEMY_DATABASE_URI = (
        f"postgresql://{POSTGRES_USER}:{POSTGRES_PW}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )

    # Secret key (fallback only for dev)
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")

    # Email
    MAIL_SERVER = "smtp.gmail.com"
    MAIL_PORT = 465
    MAIL_USE_SSL = True
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "padelleagueporto@gmail.com")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")

    # Sessions
    SESSION_PERMANENT = False
    SESSION_TYPE = "filesystem"


class DevConfig(Config):
    DEBUG = True
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")

class DevConfigProdDB(Config):
    DEBUG = True
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "35.205.246.86")


class ProdConfig(Config):
    DEBUG = False
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "172.17.0.1")
