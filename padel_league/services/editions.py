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


def preview_plan(plan):
    """What create_edition_from_plan would create, without writing anything.

    Raises EditionPlanError like validate_plan. Groups come back in plan order
    with the tier they would get (by rating, highest first).
    """
    validated = validate_plan(plan)
    ladder = sorted(validated["divisions"], key=lambda d: -d["rating"])
    return {
        "edition_name": validated["edition_name"],
        "league_id": validated["league_id"],
        "season_id": validated["season_id"],
        "event_slot_id": validated["event_slot_id"],
        "beginning_datetime": validated["beginning_datetime"].isoformat(),
        "divisions": [
            {
                "name": spec["name"],
                "tier": ladder.index(spec) + 1,
                "rating": spec["rating"],
                "starts_at": validated["beginning_datetime"].isoformat(),
                "players": list(spec["players"]),
                "logo_image_id": spec["logo_image_id"],
                "large_picture_id": spec["large_picture_id"],
            }
            for spec in validated["divisions"]
        ],
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
                # Live standings come from the views, so they are never stale
                # (the old code set this on its first GET).
                standings_up_to_date=True,
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


# --- Single writes behind the v1 admin endpoints (POST /editions, POST|PUT /divisions)


def _season_for(league_id, day=None):
    """The season containing ``day`` (today by default), else the latest one."""
    day = day or datetime.date.today()
    seasons = Season.query.filter_by(league_id=league_id)
    return (
        seasons.filter(Season.starts_on <= day, Season.ends_on >= day).first()
        or seasons.order_by(Season.starts_on.desc()).first()
    )


def _main_stage(competition_id):
    stage = Stage.query.filter_by(competition_id=competition_id, number=1).first()
    if stage is None:
        stage = Stage(competition_id=competition_id, number=1, seeding_method="promotion", emits_award=True)
        db.session.add(stage)
        db.session.flush()
    return stage


def create_classica_competition(name, league_id, actor_user_id=None):
    """An empty edition: a classica competition with its first stage. Caller commits."""
    season = _season_for(league_id)
    if season is None:
        raise EditionPlanError(f"league {league_id} has no season")
    competition = Competition(season_id=season.id, name=name, format="classica", status="planned")
    db.session.add(competition)
    db.session.flush()
    _main_stage(competition.id)
    db.session.add(
        AuditEvent(actor_user_id=actor_user_id, entity="competition", entity_id=competition.id, action="created", after={"name": name})
    )
    return competition


def _retier(stage):
    """Tier = position on the stage's ladder, highest rating first."""
    groups = CompetitionGroup.query.filter_by(stage_id=stage.id).all()
    for tier, group in enumerate(sorted(groups, key=lambda g: (-(g.rating or 0), g.id)), start=1):
        group.tier = tier


def _drop_unused_entries(competition_id):
    """Entries left with no group and no match in their competition."""
    from padel_league.models.v2 import MatchParticipant

    used = {gm.entry_id for gm in GroupMember.query.join(CompetitionGroup).join(Stage).filter(Stage.competition_id == competition_id)}
    for entry in Entry.query.filter_by(competition_id=competition_id):
        if entry.id not in used and not MatchParticipant.query.filter_by(entry_id=entry.id).first():
            db.session.delete(entry)


def save_classica_group(payload, group=None, actor_user_id=None):
    """Create or update a classica group from the v1 division payload. Caller commits.

    ``payload`` is the validated body of POST/PUT /api/v1/divisions (edition_id
    is the competition id). The member list is replaced in ``order_index``
    order, as the old code rewrote players_in_division; matches are untouched.
    """
    competition = db.session.get(Competition, payload["edition_id"])
    stage = _main_stage(competition.id)
    previous_stage = group.stage if group is not None else None
    previous_competition_id = previous_stage.competition_id if previous_stage else None
    before = None
    if group is None:
        group = CompetitionGroup(stage_id=stage.id, structure="round_robin", standings_up_to_date=True)
        db.session.add(group)
    else:
        before = {"name": group.name, "rating": group.rating, "members": [m.entry.player_id for m in group.members]}
        group.stage_id = stage.id

    group.name = payload["name"]
    group.starts_at = payload["beginning_datetime"]
    group.rating = payload["rating"]
    end_date = payload["end_date"]
    group.end_date = datetime.datetime.combine(end_date, datetime.time.min) if end_date else None
    group.has_ended = payload["has_ended"]
    group.open_division = payload["open_division"]
    group.logo_image_id = payload["logo_image_id"]
    group.large_picture_id = payload["large_picture_id"]
    db.session.flush()

    for member in list(group.members):
        db.session.delete(member)
    db.session.flush()
    db.session.expire(group, ["members"])
    for item in payload["players"]:
        entry = Entry.query.filter_by(competition_id=competition.id, player_id=item["player_id"]).first()
        if entry is None:
            entry = Entry(competition_id=competition.id, player_id=item["player_id"])
            db.session.add(entry)
            db.session.flush()
        db.session.add(GroupMember(group_id=group.id, entry_id=entry.id, seed=item["order_index"]))
    db.session.flush()

    _retier(stage)
    if previous_stage is not None and previous_stage.id != stage.id:
        _retier(previous_stage)
    for competition_id in {competition.id, previous_competition_id} - {None}:
        _drop_unused_entries(competition_id)
    db.session.add(
        AuditEvent(
            actor_user_id=actor_user_id,
            entity="group",
            entity_id=group.id,
            action="updated" if before else "created",
            before=before,
            after={"name": group.name, "rating": group.rating, "members": [i["player_id"] for i in payload["players"]]},
        )
    )
    return group
