import os
from tempfile import mkdtemp

from flask import Flask
from flask_assets import Bundle, Environment
from flask_login import LoginManager
from flask_session import Session
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from .auth import register_jwt_handlers

from . import cli, context, mail, modules, read_only, sql_db


LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


def _refuse_remote_db_outside_production(app):
    """Development must never reach the production database by accident.

    Set ALLOW_REMOTE_DB=1 to opt in deliberately.
    """
    from sqlalchemy.engine import make_url

    host = make_url(app.config["SQLALCHEMY_DATABASE_URI"]).host or ""
    if host not in LOCAL_DB_HOSTS and os.getenv("ALLOW_REMOTE_DB") != "1":
        raise RuntimeError(
            f"Refusing to start in development against database host {host!r}. "
            "Set POSTGRES_HOST=localhost, or ALLOW_REMOTE_DB=1 to override."
        )


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    CORS(
        app,
        resources={
            r"/api/v1/*": {
                "origins": [
                    "http://localhost:8080",
                    "http://35.205.246.86",
                ]
            },
            r"/api/v2/*": {
                "origins": [
                    "http://localhost:8080",
                    "http://35.205.246.86",
                ]
            },
        },
        supports_credentials=False,
        allow_headers=["Content-Type", "Authorization"],
    )

    # Load config
    env = os.getenv("FLASK_ENV", "development")
    if test_config:
        app.config.from_mapping(test_config)
    elif env == "production":
        from .config import ProdConfig

        app.config.from_object(ProdConfig)
        if not app.config.get("SECRET_KEY") or not app.config.get("JWT_SECRET_KEY"):
            raise RuntimeError("Production needs FLASK_SECRET_KEY (or SECRET_KEY and JWT_SECRET_KEY) set")
    else:
        from .config import DevConfig

        app.config.from_object(DevConfig)
        _refuse_remote_db_outside_production(app)

    read_only.init_app(app)

    # Ensure responses aren't cached
    @app.after_request
    def after_request(response):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Expires"] = 0
        response.headers["Pragma"] = "no-cache"
        return response

    with app.app_context():
        modules.startup.add_to_session()

    app.config["SESSION_FILE_DIR"] = mkdtemp()
    Session(app)

    jwt = JWTManager(app)
    register_jwt_handlers(jwt)
    app.jwt = jwt

    mail.mail.init_app(app)

    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    modules.register_blueprints(app)

    # Assets
    assets = Environment(app)
    scss_bundle = Bundle(
        "style/scss/main.scss",
        filters="pyscss",
        depends="style/scss/*.scss",
        output="style/styles.css",
    )
    assets.register("scss", scss_bundle)

    scss_bundle_backend = Bundle(
        "style/scss/main_backend.scss",
        filters="pyscss",
        depends="style/scss/*.scss",
        output="style/styles_backend.css",
    )
    assets.register("scss_backend", scss_bundle_backend)

    # Login manager
    login_manager = LoginManager(app)
    from .auth import setup_login_manager

    setup_login_manager(login_manager)
    app.login_manager = login_manager

    sql_db.init_db(app)
    cli.register_cli(app)

    @app.context_processor
    def inject_sponsors():
        return context.inject_sponsors()

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        sql_db.db.session.remove()

    return app
