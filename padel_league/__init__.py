import os 

from flask import Flask
from tempfile import mkdtemp
from flask_session import Session
from flask_assets import Environment, Bundle


from . import sql_db
from . import modules
from . import model
from . import mail

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    POSTGRES_USER = os.getenv('POSTGRES_USER', 'padel_user')
    POSTGRES_PW = os.getenv('POSTGRES_PW', 'portopadelleague')
    POSTGRES_DB = os.getenv('POSTGRES_DB', 'padel_league')
    POSTGRES_HOST = os.getenv('POSTGRES_HOST', '35.205.246.86')
    POSTGRES_PORT = os.getenv('POSTGRES_PORT', '5432')
    
    db_uri = f"postgresql://{POSTGRES_USER}:{POSTGRES_PW}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri

    app.config['SECRET_KEY'] = 'hjshjhdjah kjshkjdhjs'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    # Ensure responses aren't cached
    @app.after_request
    def after_request(response):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Expires"] = 0
        response.headers["Pragma"] = "no-cache"
        return response

    @app.before_first_request
    def before_first_request():
        modules.startup.add_to_session()

    # Configure session to use filesystem (instead of signed cookies)
    app.config["SESSION_FILE_DIR"] = mkdtemp()
    app.config["SESSION_PERMANENT"] = False
    app.config["SESSION_TYPE"] = "filesystem"
    Session(app)

    app.config.update(
        DEBUG=True,
        # Email Server Configuration
        MAIL_SERVER='smtp.gmail.com',
        MAIL_PORT=465,
        MAIL_USE_SSL=True,
        MAIL_USERNAME='padelleagueporto@gmail.com',
        MAIL_PASSWORD='mvheiqexdjewhyvy',
    )

    mail.mail.init_app(app)

    if test_config is None:
        # Load the instance config when not testing
        app.config.from_pyfile('config.py',silent=True)
    else:
        # Load the test config
        app.config.from_mapping(test_config)

    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass
    
    modules.register_blueprints(app)

    assets = Environment(app)

    scss_bundle = Bundle('style/scss/main.scss', filters='pyscss', depends='style/scss/*.scss',output='style/styles.css')
    assets.register('scss', scss_bundle)
    
    with app.app_context():
        sql_db.db.init_app(app)
        sql_db.db.create_all()

    return app