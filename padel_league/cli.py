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

    @app.cli.command("generate-artwork")
    @click.option("--edition-id", type=int, required=True)
    @click.option(
        "--kind",
        type=click.Choice(["poster", "banner", "both"]),
        default="both",
    )
    @click.option(
        "--force", is_flag=True, help="Replace artwork a division already has."
    )
    def generate_artwork(edition_id, kind, force):
        """Generate and attach division posters and banners for an edition."""
        from padel_league.models import Edition
        from padel_league.services.artwork import generate_for_edition

        kinds = ("poster", "banner") if kind == "both" else (kind,)

        with app.app_context():
            edition = Edition.query.filter_by(id=edition_id).first()
            if not edition:
                raise click.ClickException(f"edition {edition_id} was not found")
            results = generate_for_edition(edition, kinds=kinds, force=force)
            click.echo(json.dumps(results, indent=2, ensure_ascii=False))
            failed = [r for r in results if r.get("error")]
            resized = [r for r in results if r.get("was_resized")]
            if resized:
                click.echo(
                    f"{len(resized)} image(s) were not the exact size and were "
                    "cover-cropped — worth a human look."
                )
            if failed:
                raise click.ClickException(f"{len(failed)} image(s) failed")

    @app.cli.command("backfill-player-accounts")
    @click.option(
        "--dry-run", is_flag=True, help="List players missing a login, write nothing."
    )
    @click.option(
        "--player-id",
        "player_ids",
        type=int,
        multiple=True,
        help="Only these players. Omit to cover everyone missing a login.",
    )
    def backfill_player_accounts(dry_run, player_ids):
        """Give every player without a login one (username = full name, no
        spaces, lower case; password = the username)."""
        from padel_league.services.accounts import (
            ensure_user_for_player,
            players_without_accounts,
            username_for,
        )
        from padel_league.sql_db import db

        with app.app_context():
            missing = players_without_accounts()
            if player_ids:
                wanted = set(player_ids)
                found = {p.id for p in missing}
                unknown = sorted(wanted - found)
                if unknown:
                    raise click.ClickException(
                        f"player(s) {unknown} either do not exist or already "
                        "have a login"
                    )
                missing = [p for p in missing if p.id in wanted]
            if not missing:
                click.echo("Every player already has a login.")
                return
            if dry_run:
                for player in missing:
                    click.echo(
                        f"{player.id:>4}  {player.full_name or player.name}  ->  "
                        f"{username_for(player.full_name or player.name)}"
                    )
                click.echo(
                    f"{len(missing)} player(s) missing a login. Nothing written."
                )
                return
            created = []
            for player in missing:
                user, was_created = ensure_user_for_player(player, commit=False)
                if was_created:
                    created.append(user)
            db.session.commit()
            click.echo(
                json.dumps(
                    [
                        {
                            "player_id": u.player_id,
                            "username": u.username,
                            "email": u.email,
                            "password": u.username,
                        }
                        for u in created
                    ],
                    indent=2,
                    ensure_ascii=False,
                )
            )
