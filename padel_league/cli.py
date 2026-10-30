import json
import os

import click
from werkzeug.security import generate_password_hash


def register_cli(app):
    v2 = click.Group("v2", help="v2 data-model maintenance.")
    app.cli.add_command(v2)

    @v2.command("bootstrap-ranking")
    def bootstrap_ranking():
        """Award the ended Shuffle(s) and write the current ranking snapshot (idempotent)."""
        from padel_league.services import ranking
        from padel_league.sql_db import db

        for line in ranking.bootstrap():
            click.echo(line)
        db.session.commit()

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

    @app.cli.command("propose-edition")
    @click.option("--previous", "previous_id", type=int, required=True, help="Competition id of the last Clássica.")
    @click.option("--name", "edition_name", default=None,
                  help='Default "<N>ª Edição", N = next number across every format')
    @click.option("--start", "beginning", required=True, help="ISO datetime of jornada 1, e.g. 2027-01-12T21:30:00")
    @click.option("--prefix", "division_prefix", default=None, help='Division base name, e.g. "Inverno 2027"')
    @click.option("--withdrawals", default="", help="Comma-separated player ids leaving")
    @click.option("--new", "new_players", default="", help="Comma-separated new player ids, filling vacancies bottom-up")
    @click.option("--placed", default=None, help='JSON {tier: [player ids]} placed straight into a division')
    @click.option("--season", default=None)
    @click.option("--event-slot", default=None)
    @click.option("--out", "out_path", type=click.Path(dir_okay=False), required=True)
    def propose_edition(previous_id, edition_name, beginning, division_prefix, withdrawals, new_players, placed,
                        season, event_slot, out_path):
        """Write the next Clássica's plan (promotion from --previous) to --out. Writes nothing to the DB."""
        from padel_league.domain.errors import InvalidInput, Conflict, NotFound
        from padel_league.services.classica_builder import next_classica_plan
        from padel_league.services.editions import default_edition_name

        ids = lambda raw: [int(x) for x in raw.split(",") if x.strip()]  # noqa: E731
        with app.app_context():
            edition_name = edition_name or default_edition_name()
            try:
                plan, notes = next_classica_plan(
                    previous_id, edition_name, beginning,
                    withdrawals=ids(withdrawals), new_player_ids=ids(new_players),
                    placed_new_players=json.loads(placed) if placed else None,
                    season=season, event_slot=event_slot, division_prefix=division_prefix, strict=False,
                )
            except (InvalidInput, Conflict, NotFound) as exc:
                raise click.ClickException(str(exc))
        with open(out_path, "w") as handle:
            json.dump(plan, handle, indent=2, ensure_ascii=False)
        for note in notes:
            click.echo(f"note: {note}")
        click.echo(f"plan written to {out_path} ({len(plan['divisions'])} divisions); review it, then create-edition --dry-run")

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

    @app.cli.command("import-substitutes")
    @click.argument("rows_path", type=click.Path(exists=True, dir_okay=False))
    @click.argument("map_path", type=click.Path(exists=True, dir_okay=False))
    @click.option("--decisions", "decisions_path", type=click.Path(exists=True, dir_okay=False), default=None,
                  help="Per-row skip/override CSV (docs/v2/subs_row_decisions.csv).")
    @click.option("--dry-run", is_flag=True, help="Do everything in a transaction, report, roll back.")
    def import_substitutes(rows_path, map_path, decisions_path, dry_run):
        """Fill historic substitute slots from the SUBS_ sheet (run merge-players first)."""
        from padel_league.services.imports import substitutes as subs

        with app.app_context():
            try:
                report = subs.run(subs.load_rows(rows_path), subs.load_name_map(map_path),
                                  subs.load_decisions(decisions_path), dry_run=dry_run)
            except subs.ImportError_ as exc:
                raise click.ClickException(str(exc))
        skipped = report.pop("rows_skipped")
        click.echo(json.dumps(report, indent=2, ensure_ascii=False))
        for row, reason in skipped:
            click.echo(f"skipped row {row}: {reason}")

    @app.cli.command("merge-players")
    @click.option("--from", "from_id", type=int, required=True, help="The duplicate (deleted).")
    @click.option("--into", "into_id", type=int, required=True, help="The player who keeps the history.")
    @click.option("--dry-run", is_flag=True)
    def merge_players_cmd(from_id, into_id, dry_run):
        """Merge a duplicate player into another: entries, matches, awards, login. Ranking needs a recompute after."""
        from padel_league.services.imports import substitutes as subs

        with app.app_context():
            try:
                moved = subs.merge_players(from_id, into_id, dry_run=dry_run)
            except subs.ImportError_ as exc:
                raise click.ClickException(str(exc))
        click.echo(json.dumps({"from": from_id, "into": into_id, "dry_run": dry_run, "moved": moved}, indent=2))

    @app.cli.command("swap-roster-player")
    @click.option("--competition", "competition_id", type=int, required=True)
    @click.option("--out", "out_id", type=int, required=True, help="Player leaving the roster.")
    @click.option("--in-name", "in_name", required=True, help="Full name of the player joining (must exist).")
    @click.option("--dry-run", is_flag=True)
    def swap_roster_player_cmd(competition_id, out_id, in_name, dry_run):
        """Replace a player of a not-yet-drawn roster; the newcomer becomes a member with a login."""
        from padel_league.models import Player
        from padel_league.services.imports.roster import RosterError, swap_roster_player

        with app.app_context():
            player = Player.query.filter_by(full_name=in_name).first()
            if player is None:
                raise click.ClickException(f"no player with full name {in_name!r} (run import-substitutes first)")
            in_id = player.id
            try:
                done = swap_roster_player(competition_id, out_id, in_id, dry_run=dry_run)
            except RosterError as exc:
                raise click.ClickException(str(exc))
        click.echo(json.dumps({"competition": competition_id, "out": out_id, "in": in_id,
                               "dry_run": dry_run, **done}, indent=2, ensure_ascii=False))

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

    @app.cli.command("attach-artwork")
    @click.option(
        "--competition-id",
        type=int,
        required=True,
        help="The competition the groups must belong to; any other group id is refused.",
    )
    @click.option("--group-id", type=int, help="v2 competition group (division) id.")
    @click.option("--kind", type=click.Choice(["poster", "banner"]))
    @click.option("--file", "file_path", type=click.Path(exists=True, dir_okay=False), help="Local image file.")
    @click.option(
        "--manifest",
        type=click.Path(exists=True, dir_okay=False),
        help='JSON list of {"group_id", "kind", "file"}; relative files resolve beside the manifest.',
    )
    @click.option("--force", is_flag=True, help="Replace artwork the group already has.")
    def attach_artwork(competition_id, group_id, kind, file_path, manifest, force):
        """Attach local poster/banner files to v2 competition groups (Teams divisions too).

        Every group must belong to --competition-id (checked before any file is read
        or uploaded). One image per commit: a failing entry of a manifest does not
        undo the others. Prints one JSON result per image; exits 1 when any failed.
        """
        from padel_league.services import artwork

        single = (group_id, kind, file_path)
        if manifest and any(v is not None for v in single):
            raise click.UsageError("use either --manifest or --group-id/--kind/--file, not both")
        if not manifest and any(v is None for v in single):
            raise click.UsageError("--group-id, --kind and --file are all required without --manifest")

        with app.app_context():
            if manifest:
                with open(manifest, encoding="utf-8") as handle:
                    entries = json.load(handle)
                if not isinstance(entries, list):
                    raise click.ClickException("the manifest must be a JSON list")
                base = os.path.dirname(os.path.abspath(manifest))
                for entry in entries:
                    if isinstance(entry, dict) and isinstance(entry.get("file"), str) and not os.path.isabs(entry["file"]):
                        entry["file"] = os.path.join(base, entry["file"])
                results = artwork.attach_manifest(entries, force=force, competition_id=competition_id)
            else:
                try:
                    group = artwork.load_group(group_id, competition_id=competition_id)
                    results = [artwork.attach_file(group, kind, file_path, force=force)]
                except artwork.ArtworkError as exc:
                    raise click.ClickException(str(exc))
            click.echo(json.dumps(results, indent=2, ensure_ascii=False))
            failed = [r for r in results if r.get("error")]
            resized = [r for r in results if r.get("was_resized")]
            if resized:
                click.echo(
                    f"{len(resized)} image(s) were not the exact size and were cover-cropped — worth a human look."
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
