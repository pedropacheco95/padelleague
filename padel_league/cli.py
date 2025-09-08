import click
from werkzeug.security import generate_password_hash
from .sql_db import db
from padel_league.models import User, Backend_App

def register_cli(app):
    @app.cli.command("seed")
    @click.option("--admin-user", default="admin")
    @click.option("--admin-email", default="admin@example.com")
    @click.option("--admin-password", envvar="ADMIN_PASSWORD", prompt=True, hide_input=True, confirmation_prompt=True)
    def seed(admin_user, admin_email, admin_password):
        with app.app_context():
            admin = User.query.filter_by(username=admin_user).first()
            if not admin:
                admin = User(
                    username=admin_user,
                    email=admin_email,
                    password=generate_password_hash(admin_password),
                    is_admin=True,
                )
                db.session.add(admin)

            apps_app = Backend_App.query.filter_by(name='Aplicações').first()
            if not apps_app:
                apps_app = Backend_App(name='Aplicações', app_model_name='Backend_App')
                db.session.add(apps_app)

            db.session.commit()
            click.echo("Seeding done.")
