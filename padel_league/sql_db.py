from flask import url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash

db = SQLAlchemy()

from padel_league.models import User, Backend_App

def init_db(app):
    db.init_app(app)
    db.create_all()

    # Ensure there's always an admin user
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(username='admin', email='admin@example.com', password=generate_password_hash('admin'), is_admin=True)
        admin.create()

    apps_app = Backend_App.query.filter_by(name='Aplicações').first()
    if not apps_app:
        apps_app = Backend_App(name='Aplicações',app_model_name='Backend_App')
        apps_app.create()