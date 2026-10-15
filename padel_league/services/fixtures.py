"""Fixture generation for a division.

A division is always 8 players playing 7 jornadas. Each jornada has 4 fixed
pairs playing a full round-robin between them (6 jogos), split across two
courts. The pairings live in ``tools/games_order.json``, which is a
1-factorisation of 8 players: over the 7 jornadas every player partners every
other player exactly once, and plays 3 jogos per jornada (21 in total).

The JSON file is written in terms of abstract seats ("Player 1".."Player 8").
Generating fixtures means shuffling the group's members into those seats and
materialising the resulting v2 rows: the stage's rounds (one per jornada,
shared by every group of the stage), matches and match participants.
"""

import datetime
import json
import os
import random

from flask import current_app

from padel_league.models.v2 import (
    AuditEvent,
    CompetitionGroup,
    CompetitionMatch,
    MatchParticipant,
    Round,
)
from padel_league.sql_db import db

PLAYERS_PER_DIVISION = 8
MATCHWEEK_COUNT = 7
GAMES_PER_MATCHWEEK = 6
DEFAULT_FIELDS = ("Campo 1", "Campo 2")
COURTS_PER_DIVISION = 2


class FixtureGenerationError(Exception):
    """A division cannot have its fixtures generated."""


def load_games_order():
    """Load and validate the pairing template."""
    path = os.path.join(current_app.root_path, "tools", "games_order.json")
    with open(path) as handle:
        matchweeks = json.load(handle)

    seats = {f"Player {i + 1}" for i in range(PLAYERS_PER_DIVISION)}
    if len(matchweeks) != MATCHWEEK_COUNT:
        raise FixtureGenerationError(
            f"games_order.json must define {MATCHWEEK_COUNT} matchweeks, "
            f"found {len(matchweeks)}"
        )

    for key, games in matchweeks.items():
        if len(games) != GAMES_PER_MATCHWEEK:
            raise FixtureGenerationError(
                f"matchweek {key} must define {GAMES_PER_MATCHWEEK} games, "
                f"found {len(games)}"
            )
        for game in games:
            home, away = game
            unknown = (set(home) | set(away)) - seats
            if unknown:
                raise FixtureGenerationError(
                    f"matchweek {key} references unknown seats: {sorted(unknown)}"
                )

    return matchweeks


def fields_for(group):
    """The two courts this group plays on.

    All groups of a stage play at the same time, one pair of courts each: 1ª on
    Campos 1-2, 2ª on 3-4, ... 6ª on 11-12. The pair is derived from the group's
    position on the ladder (highest rating first), so it follows the stage's
    shape rather than needing to be configured.

    A group with no stage keeps the old Campo 1 / Campo 2.
    """
    stage = group.stage
    if stage is None:
        return DEFAULT_FIELDS
    ladder = sorted(stage.groups, key=lambda g: (-(g.rating or 0), (g.name or "").lower()))
    try:
        index = ladder.index(group)
    except ValueError:
        return DEFAULT_FIELDS
    first = index * COURTS_PER_DIVISION + 1
    return tuple(f"Campo {first + n}" for n in range(COURTS_PER_DIVISION))


def _stage_rounds(stage, beginning):
    """The stage's jornadas 1..7, created when missing. Rounds are per stage."""
    rounds = {r.number: r for r in Round.query.filter_by(stage_id=stage.id)}
    for number in range(1, MATCHWEEK_COUNT + 1):
        if number not in rounds:
            rounds[number] = Round(stage_id=stage.id, number=number)
            db.session.add(rounds[number])
        if rounds[number].date is None:
            rounds[number].date = (beginning + datetime.timedelta(days=7 * (number - 1))).date()
    db.session.flush()
    return rounds


def _delete_existing_matches(matches):
    """Remove matches (participants and sets cascade). Caller commits."""
    for match in matches:
        db.session.delete(match)
    db.session.flush()


def generate_group_fixtures(group, force=False, rng=None, commit=True, fields=None, actor_user_id=None):
    """Create the full fixture list for a classica ``group`` (CompetitionGroup).

    Runs as a single transaction. Returns a summary dict including the
    seat -> player mapping, which is otherwise unrecoverable because the draw
    is random.

    Pass ``commit=False`` to leave the work pending in the session, so a caller
    building several groups can commit them as one unit. ``fields`` overrides
    the courts; by default they come from the group's ladder position.

    Raises FixtureGenerationError when the group is not in a state where
    fixtures can be generated (wrong player count, no start date, or matches
    that already exist without ``force``). Regeneration is always refused once
    any match has been played.
    """
    if group.starts_at is None:
        raise FixtureGenerationError(f"division {group.id} has no beginning_datetime")

    entries = {m.entry.player_id: m.entry for m in group.members}
    player_ids = sorted(entries)
    if len(player_ids) != PLAYERS_PER_DIVISION:
        raise FixtureGenerationError(
            f"division {group.id} must have exactly {PLAYERS_PER_DIVISION} "
            f"distinct players, found {len(player_ids)}"
        )

    existing = CompetitionMatch.query.filter_by(group_id=group.id).all()
    if existing:
        if not force:
            raise FixtureGenerationError(
                f"division {group.id} already has {len(existing)} matches; "
                "pass force=True to regenerate"
            )
        played = [match for match in existing if match.played]
        if played:
            raise FixtureGenerationError(
                f"refusing to regenerate division {group.id}: "
                f"{len(played)} matches have already been played"
            )

    matchweeks = load_games_order()
    fields = tuple(fields) if fields else fields_for(group)

    # The draw is random by design — the same players get different partners
    # each edition. `seats` is returned so the draw stays auditable.
    draw = list(player_ids)
    (rng or random).shuffle(draw)
    seats = {f"Player {i + 1}": player_id for i, player_id in enumerate(draw)}

    if existing:
        _delete_existing_matches(existing)

    rounds = _stage_rounds(group.stage, group.starts_at)
    created = 0
    for key in sorted(matchweeks, key=int):
        matchweek = int(key)
        date_hour = group.starts_at + datetime.timedelta(days=7 * (matchweek - 1))
        for index, (home, away) in enumerate(matchweeks[key]):
            match = CompetitionMatch(
                group_id=group.id,
                round_id=rounds[matchweek].id,
                scheduled_at=date_hour,
                court=fields[index % len(fields)],
                status="scheduled",
            )
            db.session.add(match)
            db.session.flush()  # need match.id for the participants

            for seat_keys, side in ((home, "home"), (away, "away")):
                for slot, seat in enumerate(seat_keys, start=1):
                    entry = entries[seats[seat]]
                    db.session.add(
                        MatchParticipant(
                            match_id=match.id,
                            side=side,
                            slot=slot,
                            role="member",
                            entry_id=entry.id,
                            player_id=entry.player_id,
                        )
                    )
            created += 1

    # The edition ends on the last jornada, not a week later.
    last_matchweek = group.starts_at + datetime.timedelta(days=7 * (MATCHWEEK_COUNT - 1))
    group.end_date = datetime.datetime.combine(last_matchweek.date(), datetime.time.min)
    db.session.add(
        AuditEvent(
            actor_user_id=actor_user_id,
            entity="group",
            entity_id=group.id,
            action="fixtures_generated",
            after={"matches": created, "fields": list(fields), "seats": seats, "replaced": len(existing)},
        )
    )

    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    else:
        db.session.flush()

    return {
        "division_id": group.id,
        "division_name": group.name,
        "matches_created": created,
        "matchweeks": MATCHWEEK_COUNT,
        "beginning_datetime": group.starts_at.isoformat(),
        "fields": list(fields),
        "end_date": last_matchweek.date().isoformat(),
        "seats": seats,
    }


def generate_division_fixtures(division, force=False, rng=None, commit=True, fields=None, actor_user_id=None):
    """v1 entry point: ``division`` is a compat Division (or a group); its id is the group id."""
    group = division if isinstance(division, CompetitionGroup) else db.session.get(CompetitionGroup, division.id)
    if group is None:
        raise FixtureGenerationError(f"division {division.id} was not found")
    return generate_group_fixtures(
        group, force=force, rng=rng, commit=commit, fields=fields, actor_user_id=actor_user_id
    )
