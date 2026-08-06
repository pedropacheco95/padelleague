import json

import click
from werkzeug.security import generate_password_hash


def register_cli(app):
    @app.cli.command("generate-fixtures")
    @click.option("--division-id", type=int, required=True)
    @click.option(
        "--force",
        is_flag=True,
        help="Regenerate over existing matches (refused once any is played).",
    )
    def generate_fixtures(division_id, force):
        """Create the 7 jornadas x 6 jogos for a division."""
        from padel_league.models import Division
        from padel_league.services.fixtures import (
            FixtureGenerationError,
            generate_division_fixtures,
        )

        with app.app_context():
            division = Division.query.filter_by(id=division_id).first()
            if not division:
                raise click.ClickException(f"division {division_id} was not found")
            try:
                summary = generate_division_fixtures(division, force=force)
            except FixtureGenerationError as exc:
                raise click.ClickException(str(exc))
            click.echo(json.dumps(summary, indent=2, ensure_ascii=False))

    @app.cli.command("create-edition")
    @click.option(
        "--plan",
        "plan_path",
        type=click.Path(exists=True, dir_okay=False),
        required=True,
        help="JSON plan describing the edition, its divisions and their players.",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Validate the plan against the database without writing anything.",
    )
    def create_edition(plan_path, dry_run):
        """Create an edition with its divisions, players and fixtures."""
        from padel_league.services.editions import (
            EditionPlanError,
            create_edition_from_plan,
            validate_plan,
        )

        with open(plan_path) as handle:
            plan = json.load(handle)

        with app.app_context():
            try:
                if dry_run:
                    validated = validate_plan(plan)
                    click.echo(
                        "Plan is valid: "
                        f"{validated['edition_name']} — "
                        f"{len(validated['divisions'])} divisions, "
                        f"{sum(len(d['players']) for d in validated['divisions'])} "
                        "players. Nothing was written."
                    )
                    return
                result = create_edition_from_plan(plan)
            except EditionPlanError as exc:
                raise click.ClickException(str(exc))
            click.echo(json.dumps(result, indent=2, ensure_ascii=False))

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
