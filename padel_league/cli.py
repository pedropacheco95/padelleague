import click
from werkzeug.security import generate_password_hash


def register_cli(app):
    @app.cli.command("seed")
    @click.option("--admin-user", default="admin")
    @click.option("--admin-email", default="admin@example.com")
    @click.option(
        "--admin-password",
        envvar="ADMIN_PASSWORD",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
    )
    def seed(admin_user, admin_email, admin_password):
        from padel_league.models import Backend_App, User

        with app.app_context():
            admin = User.query.filter_by(username=admin_user).first()
            if not admin:
                admin = User(
                    username=admin_user,
                    email=admin_email,
                    password=generate_password_hash(admin_password),
                    is_admin=True,
                )
                admin.create()

            apps_app = Backend_App.query.filter_by(name="Aplicações").first()
            if not apps_app:
                apps_app = Backend_App(name="Aplicações", app_model_name="Backend_App")
                apps_app.create()

            click.echo("Seeding done.")
