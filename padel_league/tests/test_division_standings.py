import itertools
import os
import tempfile
from datetime import datetime, timedelta

import pytest

from padel_league import create_app
from padel_league.models import (
    Association_PlayerDivision,
    Association_PlayerMatch,
    Division,
    Match,
    Player,
)
from padel_league.modules.frontend_api.v1.serializers import serialize_standings_row
from padel_league.sql_db import db, init_db

# The shared `app` fixture in conftest.py runs `db.create_all()` against the
# full metadata, which fails on SQLite: several association tables
# (e.g. `players_in_match`, `players_in_division`, and unrelated
# `product_attributes_in_product`) declare an autoincrement `id` alongside a
# composite primary key, a pattern Postgres (the real backend) accepts but
# SQLite's DDL compiler rejects outright ("SQLite does not support
# autoincrement for composite primary keys"). Rather than touch those model
# definitions (used in prod via Alembic migrations, never via create_all),
# this fixture creates only the tables this test suite needs and disables
# the `autoincrement` flag on the two composite-pk association tables just
# for SQLite DDL purposes, restoring it afterwards. Rows on those two tables
# are given an explicit `id` in this file's helpers since SQLite won't
# auto-assign one for a composite primary key.
_COMPOSITE_PK_TABLES_WITH_AUTOINCREMENT = [
    Association_PlayerMatch.__table__,
    Association_PlayerDivision.__table__,
]


@pytest.fixture
def app():
    db_fd, db_path = tempfile.mkstemp()

    original_autoincrement = [
        table.c.id.autoincrement for table in _COMPOSITE_PK_TABLES_WITH_AUTOINCREMENT
    ]
    for table in _COMPOSITE_PK_TABLES_WITH_AUTOINCREMENT:
        table.c.id.autoincrement = False

    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        }
    )

    with app.app_context():
        init_db(app)
        db.metadata.create_all(
            bind=db.engine,
            tables=[
                Division.__table__,
                Player.__table__,
                Match.__table__,
                Association_PlayerMatch.__table__,
                Association_PlayerDivision.__table__,
            ],
        )

    yield app

    os.close(db_fd)
    os.unlink(db_path)
    for table, value in zip(
        _COMPOSITE_PK_TABLES_WITH_AUTOINCREMENT, original_autoincrement
    ):
        table.c.id.autoincrement = value


_assoc_match_id_seq = itertools.count(1)
_assoc_division_id_seq = itertools.count(1)


def _make_player(name):
    player = Player(name=name)
    db.session.add(player)
    return player


def _add_player_to_division(player, division):
    db.session.add(
        Association_PlayerDivision(
            id=next(_assoc_division_id_seq),
            player_id=player.id,
            division_id=division.id,
        )
    )


def _make_match(
    division,
    matchweek,
    played,
    games_home=None,
    games_away=None,
    winner=None,
    home=(),
    away=(),
):
    match = Match(
        division=division,
        matchweek=matchweek,
        played=played,
        games_home_team=games_home,
        games_away_team=games_away,
        winner=winner,
        date_hour=datetime.now() + timedelta(days=matchweek),
    )
    db.session.add(match)
    db.session.flush()

    for player in home:
        db.session.add(
            Association_PlayerMatch(
                id=next(_assoc_match_id_seq),
                match_id=match.id,
                player_id=player.id,
                team="Home",
            )
        )
    for player in away:
        db.session.add(
            Association_PlayerMatch(
                id=next(_assoc_match_id_seq),
                match_id=match.id,
                player_id=player.id,
                team="Away",
            )
        )
    return match


def _standings_by_player_name(division):
    """Builds {player_name: serialized_row} using the same code path the API uses."""
    rows = [
        serialize_standings_row(rel, position)
        for position, rel in enumerate(
            division.players_relations_classification(), start=1
        )
    ]
    return {row["player"]["name"]: row for row in rows}


def test_standings_include_appearances_wins_draws_losses_and_games(app):
    """A player with a win, a draw and a loss across a matchweek should have
    correct appearances/wins/draws/losses/games_won/games_lost, and the
    opposing pair should show the complementary results. A player added to
    the division but never scheduled in a match should show all zeros
    (not error / not be missing)."""
    with app.app_context():
        division = Division(name="Division 1")
        db.session.add(division)
        db.session.flush()

        p1 = _make_player("P1")
        p2 = _make_player("P2")
        p3 = _make_player("P3")
        p4 = _make_player("P4")
        p5 = _make_player("P5")  # never plays a match
        db.session.flush()

        for player in (p1, p2, p3, p4, p5):
            _add_player_to_division(player, division)
        db.session.commit()

        # Matchweek 1: three matches between the same two pairs -
        # P1/P2 win one, draw one, lose one. P3/P4 get the complement.
        _make_match(
            division,
            matchweek=1,
            played=True,
            games_home=6,
            games_away=3,
            winner=1,
            home=(p1, p2),
            away=(p3, p4),
        )
        _make_match(
            division,
            matchweek=1,
            played=True,
            games_home=4,
            games_away=4,
            winner=0,
            home=(p1, p2),
            away=(p3, p4),
        )
        _make_match(
            division,
            matchweek=1,
            played=True,
            games_home=2,
            games_away=6,
            winner=-1,
            home=(p1, p2),
            away=(p3, p4),
        )
        # An unplayed match in a future matchweek keeps the division "in
        # progress" so update_table doesn't try to close it out / touch
        # edition.league (division.edition is intentionally None here).
        _make_match(division, matchweek=2, played=False, home=(p1, p2), away=(p3, p4))
        db.session.commit()

        division.update_table(force_update=True)

        standings = _standings_by_player_name(division)

        for name in ("P1", "P2"):
            row = standings[name]
            assert row["appearances"] == 1  # 3 raw match rows == 1 matchweek
            assert row["wins"] == 1
            assert row["draws"] == 1
            assert row["losts"] == 1
            assert row["gamesWon"] == 6 + 4 + 2
            assert row["gamesLost"] == 3 + 4 + 6
            assert row["points"] == 3 * 1 + 1 * 1

        for name in ("P3", "P4"):
            row = standings[name]
            assert row["appearances"] == 1
            assert row["wins"] == 1
            assert row["draws"] == 1
            assert row["losts"] == 1
            assert row["gamesWon"] == 3 + 4 + 6
            assert row["gamesLost"] == 6 + 4 + 2
            assert row["points"] == 3 * 1 + 1 * 1

        # Edge case: player never scheduled in any match for this division.
        row = standings["P5"]
        assert row["appearances"] == 0
        assert row["wins"] == 0
        assert row["draws"] == 0
        assert row["losts"] == 0
        assert row["gamesWon"] == 0
        assert row["gamesLost"] == 0
        assert row["points"] == 0


def test_standings_preserve_existing_points_based_ordering(app):
    """Adding the new stat columns must not change the ranking: the row
    order coming out of players_relations_classification() (points desc,
    unchanged logic) must match the order the new fields are attached to."""
    with app.app_context():
        division = Division(name="Division 2")
        db.session.add(division)
        db.session.flush()

        winner = _make_player("Winner")
        loser = _make_player("Loser")
        db.session.flush()

        for player in (winner, loser):
            _add_player_to_division(player, division)
        db.session.commit()

        _make_match(
            division,
            matchweek=1,
            played=True,
            games_home=6,
            games_away=0,
            winner=1,
            home=(winner,),
            away=(loser,),
        )
        _make_match(division, matchweek=2, played=False, home=(winner,), away=(loser,))
        db.session.commit()

        division.update_table(force_update=True)

        ordered_relations = division.players_relations_classification()
        ordered_names = [rel.player.name for rel in ordered_relations]
        assert ordered_names == ["Winner", "Loser"]

        rows = [
            serialize_standings_row(rel, position)
            for position, rel in enumerate(ordered_relations, start=1)
        ]
        assert [row["player"]["name"] for row in rows] == ["Winner", "Loser"]
        assert rows[0]["points"] > rows[1]["points"]
