import os
from tempfile import mkdtemp

from flask import Flask
from flask_assets import Bundle, Environment
from flask_login import LoginManager
from flask_session import Session

from . import cli, context, mail, modules, sql_db


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    # Load config
    env = os.getenv("FLASK_ENV", "development")
    if test_config:
        app.config.from_mapping(test_config)
    elif env == "production":
        from .config import ProdConfig

        app.config.from_object(ProdConfig)
    else:
        from .config import DevConfig

        app.config.from_object(DevConfig)

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
