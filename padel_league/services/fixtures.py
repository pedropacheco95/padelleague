"""Fixture generation for a division.

A division is always 8 players playing 7 jornadas. Each jornada has 4 fixed
pairs playing a full round-robin between them (6 jogos), split across two
courts. The pairings live in ``tools/games_order.json``, which is a
1-factorisation of 8 players: over the 7 jornadas every player partners every
other player exactly once, and plays 3 jogos per jornada (21 in total).

The JSON file is written in terms of abstract seats ("Player 1".."Player 8").
Generating fixtures means shuffling the division's players into those seats and
materialising the resulting Match / Association_PlayerMatch rows.
"""

import datetime
import json
import os
import random

from flask import current_app

from padel_league.models import Association_PlayerMatch, Match
from padel_league.sql_db import db

PLAYERS_PER_DIVISION = 8
MATCHWEEK_COUNT = 7
GAMES_PER_MATCHWEEK = 6
FIELDS = ("Campo 1", "Campo 2")


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


def _delete_existing_matches(matches):
    """Remove matches and their player associations. Caller commits.

    Deletes through the ORM rather than in bulk so the session's identity map
    stays consistent with the replacements inserted straight afterwards. Only
    ever runs on a forced regenerate, so the row count is trivial.
    """
    for match in matches:
        for relation in list(match.players_relations):
            db.session.delete(relation)
        db.session.delete(match)
    db.session.flush()


def generate_division_fixtures(division, force=False, rng=None, commit=True):
    """Create the full fixture list for ``division``.

    Runs as a single transaction. Returns a summary dict including the
    seat -> player mapping, which is otherwise unrecoverable because the draw
    is random.

    Pass ``commit=False`` to leave the work pending in the session, so a caller
    building several divisions can commit them as one unit.

    Raises FixtureGenerationError when the division is not in a state where
    fixtures can be generated (wrong player count, no start date, or matches
    that already exist without ``force``). Regeneration is always refused once
    any match has been played.
    """
    if division.beginning_datetime is None:
        raise FixtureGenerationError(
            f"division {division.id} has no beginning_datetime"
        )

    player_ids = sorted({rel.player_id for rel in division.players_relations})
    if len(player_ids) != PLAYERS_PER_DIVISION:
        raise FixtureGenerationError(
            f"division {division.id} must have exactly {PLAYERS_PER_DIVISION} "
            f"distinct players, found {len(player_ids)}"
        )

    existing = list(division.matches)
    if existing:
        if not force:
            raise FixtureGenerationError(
                f"division {division.id} already has {len(existing)} matches; "
                "pass force=True to regenerate"
            )
        played = [match for match in existing if match.played]
        if played:
            raise FixtureGenerationError(
                f"refusing to regenerate division {division.id}: "
                f"{len(played)} matches have already been played"
            )

    matchweeks = load_games_order()

    # The draw is random by design — the same players get different partners
    # each edition. `seats` is returned so the draw stays auditable.
    draw = list(player_ids)
    (rng or random).shuffle(draw)
    seats = {f"Player {i + 1}": player_id for i, player_id in enumerate(draw)}

    if existing:
        _delete_existing_matches(existing)

    created = 0
    for key in sorted(matchweeks, key=int):
        matchweek = int(key)
        date_hour = division.beginning_datetime + datetime.timedelta(
            days=7 * (matchweek - 1)
        )
        for index, (home, away) in enumerate(matchweeks[key]):
            match = Match(
                division_id=division.id,
                date_hour=date_hour,
                matchweek=matchweek,
                field=FIELDS[index % len(FIELDS)],
                played=False,
            )
            db.session.add(match)
            db.session.flush()  # need match.id for the associations

            for seat_keys, team in ((home, "Home"), (away, "Away")):
                for seat in seat_keys:
                    db.session.add(
                        Association_PlayerMatch(
                            player_id=seats[seat], match_id=match.id, team=team
                        )
                    )
            created += 1

    # The edition ends on the last jornada, not a week later.
    last_matchweek = division.beginning_datetime + datetime.timedelta(
        days=7 * (MATCHWEEK_COUNT - 1)
    )
    division.end_date = last_matchweek.date()

    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    else:
        db.session.flush()

    return {
        "division_id": division.id,
        "division_name": division.name,
        "matches_created": created,
        "matchweeks": MATCHWEEK_COUNT,
        "beginning_datetime": division.beginning_datetime.isoformat(),
        "end_date": division.end_date.isoformat(),
        "seats": seats,
    }
