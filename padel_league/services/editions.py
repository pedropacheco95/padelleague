"""Create a whole edition — divisions, players and fixtures — from a plan.

The plan is a plain dict (normally a reviewed JSON file) describing the new
edition. It is the artifact a human approves before anything is written, so
validation is deliberately strict and happens up front: either the entire
edition is created or nothing is.
"""

import datetime

from padel_league.models import (
    Association_PlayerDivision,
    Division,
    Edition,
    League,
    Player,
)
from padel_league.services.fixtures import (
    PLAYERS_PER_DIVISION,
    generate_division_fixtures,
)
from padel_league.sql_db import db


class EditionPlanError(Exception):
    """The plan is not valid, or conflicts with what is already in the database."""


def _parse_datetime(value):
    try:
        return datetime.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise EditionPlanError(
            f"beginning_datetime must be an ISO datetime, got {value!r}"
        )


def validate_plan(plan):
    """Check the plan against itself and against the database.

    Returns the normalised plan. Raises EditionPlanError on the first problem,
    so the message always names one concrete thing to fix.
    """
    if not isinstance(plan, dict):
        raise EditionPlanError("plan must be a JSON object")

    edition_name = (plan.get("edition_name") or "").strip()
    if not edition_name:
        raise EditionPlanError("edition_name is required")
    if Edition.query.filter_by(name=edition_name).first():
        raise EditionPlanError(f"an edition named {edition_name!r} already exists")

    league_id = plan.get("league_id")
    if league_id is None:
        league = League.query.order_by(League.id.asc()).first()
        if not league:
            raise EditionPlanError("no league exists to attach the edition to")
        league_id = league.id
    elif not League.query.filter_by(id=league_id).first():
        raise EditionPlanError(f"league_id {league_id} was not found")

    beginning = _parse_datetime(plan.get("beginning_datetime"))

    divisions = plan.get("divisions")
    if not isinstance(divisions, list) or not divisions:
        raise EditionPlanError("divisions must be a non-empty list")

    seen_names = set()
    seen_players = {}
    normalised = []

    for index, division in enumerate(divisions, start=1):
        name = (division.get("name") or "").strip()
        if not name:
            raise EditionPlanError(f"division {index} has no name")
        if name in seen_names:
            raise EditionPlanError(f"duplicate division name in plan: {name!r}")
        if Division.query.filter_by(name=name).first():
            raise EditionPlanError(
                f"a division named {name!r} already exists — division names are unique"
            )
        seen_names.add(name)

        players = division.get("players") or []
        if len(players) != PLAYERS_PER_DIVISION:
            raise EditionPlanError(
                f"{name}: expected {PLAYERS_PER_DIVISION} players, got {len(players)}"
            )
        if len(set(players)) != len(players):
            raise EditionPlanError(f"{name}: the same player appears twice")

        for player_id in players:
            if player_id in seen_players:
                raise EditionPlanError(
                    f"player {player_id} is in both {seen_players[player_id]!r} "
                    f"and {name!r}"
                )
            seen_players[player_id] = name

        rating = division.get("rating")
        if rating is None:
            raise EditionPlanError(f"{name}: rating is required")

        normalised.append(
            {"name": name, "rating": int(rating), "players": list(players)}
        )

    found = {
        player.id for player in Player.query.filter(Player.id.in_(seen_players)).all()
    }
    missing = sorted(set(seen_players) - found)
    if missing:
        raise EditionPlanError(f"player(s) not found: {missing}")

    return {
        "edition_name": edition_name,
        "league_id": league_id,
        "beginning_datetime": beginning,
        "divisions": normalised,
    }


def create_edition_from_plan(plan):
    """Create the edition, its divisions, the player assignments and fixtures.

    Everything is validated before the first write. Any failure rolls the whole
    edition back, so a partial edition is never left behind.
    """
    validated = validate_plan(plan)

    try:
        edition = Edition(
            name=validated["edition_name"], league_id=validated["league_id"]
        )
        db.session.add(edition)
        db.session.flush()

        created = []
        for spec in validated["divisions"]:
            division = Division(
                edition_id=edition.id,
                name=spec["name"],
                beginning_datetime=validated["beginning_datetime"],
                rating=spec["rating"],
                has_ended=False,
                open_division=False,
            )
            db.session.add(division)
            db.session.flush()

            for place, player_id in enumerate(spec["players"], start=1):
                db.session.add(
                    Association_PlayerDivision(
                        player_id=player_id, division_id=division.id, place=place
                    )
                )
            db.session.flush()
            created.append(division)

        # commit=False so a failure on the last division still rolls back the
        # first — a half-built edition is worse than none.
        summaries = [
            generate_division_fixtures(division, commit=False) for division in created
        ]
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return {
        "edition_id": edition.id,
        "edition_name": edition.name,
        "divisions": summaries,
    }
