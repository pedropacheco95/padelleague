"""Create a whole Clássica edition — groups, players and fixtures — from a plan.

The plan is a plain dict (normally a reviewed JSON file) describing the new
edition. It is the artifact a human approves before anything is written, so
validation is deliberately strict and happens up front: either the entire
edition is created or nothing is.

On v2 an edition is a classica competition with one stage (seeded by
promotion, emits awards) whose groups are the divisions; every player gets an
entry in the competition and a member row in their group. Optional plan keys:
``season`` (name, otherwise the season containing ``beginning_datetime``) and
``event_slot`` (key such as ``classica-2``; never inferred).
"""

import datetime

from padel_league.model import Image
from padel_league.models import League, Player
from padel_league.models.v2 import (
    AuditEvent,
    Competition,
    CompetitionGroup,
    Entry,
    EventSlot,
    GroupMember,
    Season,
    Stage,
)
from padel_league.services.fixtures import (
    MATCHWEEK_COUNT,
    PLAYERS_PER_DIVISION,
    generate_group_fixtures,
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
    if Competition.query.filter_by(name=edition_name, format="classica").first():
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

    seasons = Season.query.filter_by(league_id=league_id)
    if plan.get("season"):
        season = seasons.filter_by(name=plan["season"]).first()
        if not season:
            raise EditionPlanError(f"season {plan['season']!r} was not found")
    else:
        day = beginning.date()
        season = seasons.filter(Season.starts_on <= day, Season.ends_on >= day).first()
        if not season:
            raise EditionPlanError(f"no season contains {day}; pass \"season\" in the plan")

    event_slot_id = None
    if plan.get("event_slot"):
        slot = EventSlot.query.filter_by(key=plan["event_slot"]).first()
        if not slot or slot.format != "classica":
            raise EditionPlanError(f"event_slot {plan['event_slot']!r} is not a classica slot")
        event_slot_id = slot.id

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
        if CompetitionGroup.query.filter_by(name=name).first():
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

        # Artwork is optional here — it is normally generated afterwards by
        # `flask generate-artwork`, but a plan may point at existing images.
        images = {}
        for key in ("logo_image_id", "large_picture_id"):
            value = division.get(key)
            if value is None:
                images[key] = None
                continue
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise EditionPlanError(f"{name}: {key} must be an integer")
            if not Image.query.filter_by(id=value).first():
                raise EditionPlanError(f"{name}: {key} {value} was not found")
            images[key] = value

        normalised.append(
            {
                "name": name,
                "rating": int(rating),
                "players": list(players),
                **images,
            }
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
        "season_id": season.id,
        "event_slot_id": event_slot_id,
        "beginning_datetime": beginning,
        "divisions": normalised,
    }


def create_edition_from_plan(plan, actor_user_id=None, rng=None):
    """Create the competition, its stage, groups, entries, members and fixtures.

    Everything is validated before the first write. Any failure rolls the whole
    edition back, so a partial edition is never left behind.
    """
    validated = validate_plan(plan)
    beginning = validated["beginning_datetime"]

    try:
        competition = Competition(
            season_id=validated["season_id"],
            event_slot_id=validated["event_slot_id"],
            name=validated["edition_name"],
            format="classica",
            status="planned",
            starts_on=beginning.date(),
            ends_on=(beginning + datetime.timedelta(days=7 * (MATCHWEEK_COUNT - 1))).date(),
        )
        db.session.add(competition)
        db.session.flush()
        stage = Stage(
            competition_id=competition.id,
            number=1,
            seeding_method="promotion",
            emits_award=True,
            status="planned",
        )
        db.session.add(stage)
        db.session.flush()

        ladder = sorted(validated["divisions"], key=lambda d: -d["rating"])
        created = []
        for spec in validated["divisions"]:
            group = CompetitionGroup(
                stage_id=stage.id,
                tier=ladder.index(spec) + 1,
                name=spec["name"],
                structure="round_robin",
                starts_at=beginning,
                rating=spec["rating"],
                has_ended=False,
                open_division=False,
                logo_image_id=spec["logo_image_id"],
                large_picture_id=spec["large_picture_id"],
            )
            db.session.add(group)
            db.session.flush()

            # Members in plan order: the live standings break the all-zero tie
            # by member id, which reproduces the old `place` = plan order.
            for place, player_id in enumerate(spec["players"], start=1):
                entry = Entry(competition_id=competition.id, player_id=player_id, kind="regular", status="active")
                db.session.add(entry)
                db.session.flush()
                db.session.add(GroupMember(group_id=group.id, entry_id=entry.id, seed=place))
            db.session.flush()
            created.append(group)

        db.session.add(
            AuditEvent(
                actor_user_id=actor_user_id,
                entity="competition",
                entity_id=competition.id,
                action="created_from_plan",
                after={"name": competition.name, "groups": [g.id for g in created]},
            )
        )
        # commit=False so a failure on the last group still rolls back the
        # first — a half-built edition is worse than none.
        db.session.expire(stage, ["groups"])
        summaries = [
            generate_group_fixtures(group, commit=False, rng=rng, actor_user_id=actor_user_id)
            for group in created
        ]
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return {
        "edition_id": competition.id,
        "edition_name": competition.name,
        "divisions": summaries,
    }
