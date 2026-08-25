import itertools
import os
import tempfile

import pytest
from sqlalchemy import event

from padel_league import create_app
from padel_league.models import (
    Association_PlayerDivision,
    Association_PlayerMatch,
    Division,
    Edition,
    League,
    Match,
    Player,
)
from padel_league.services.editions import (
    EditionPlanError,
    create_edition_from_plan,
    validate_plan,
)
from padel_league.sql_db import db, init_db

# Same SQLite composite-pk workaround as test_fixture_generation.py.
_COMPOSITE_PK_TABLES_WITH_AUTOINCREMENT = [
    Association_PlayerMatch.__table__,
    Association_PlayerDivision.__table__,
]

START = "2026-09-15T21:30:00"


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
                League.__table__,
                Edition.__table__,
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
    for table, autoincrement in zip(
        _COMPOSITE_PK_TABLES_WITH_AUTOINCREMENT, original_autoincrement
    ):
        table.c.id.autoincrement = autoincrement


_assoc_ids = itertools.count(1)


@event.listens_for(Association_PlayerMatch, "before_insert", propagate=True)
@event.listens_for(Association_PlayerDivision, "before_insert", propagate=True)
def _assign_assoc_id(_mapper, _connection, target):
    if target.id is None:
        target.id = next(_assoc_ids)


def _seed(app, player_count=16):
    with app.app_context():
        league = League(name="Padel League")
        db.session.add(league)
        db.session.flush()
        player_ids = []
        for i in range(player_count):
            player = Player(name=f"Jogador {i + 1}")
            db.session.add(player)
            db.session.flush()
            player_ids.append(player.id)
        db.session.commit()
        return league.id, player_ids


def _plan(league_id, player_ids, divisions=2, **overrides):
    plan = {
        "edition_name": "22ª Edição",
        "league_id": league_id,
        "beginning_datetime": START,
        "divisions": [
            {
                "name": f"Outono 2026 - {i + 1}ª Divisão",
                "rating": 2000 // (2**i),
                "players": player_ids[i * 8 : (i + 1) * 8],
            }
            for i in range(divisions)
        ],
    }
    plan.update(overrides)
    return plan


def test_creates_edition_divisions_players_and_fixtures(app):
    league_id, player_ids = _seed(app)

    with app.app_context():
        result = create_edition_from_plan(_plan(league_id, player_ids))

    assert len(result["divisions"]) == 2
    assert all(d["matches_created"] == 42 for d in result["divisions"])

    with app.app_context():
        edition = Edition.query.get(result["edition_id"])
        assert edition.name == "22ª Edição"
        assert len(edition.divisions) == 2
        for division in edition.divisions:
            assert len(division.players_relations) == 8
            assert len(division.matches) == 42
            # place is the seeding order from the plan, 1..8
            places = sorted(rel.place for rel in division.players_relations)
            assert places == list(range(1, 9))


def test_ratings_and_dates_come_from_the_plan(app):
    league_id, player_ids = _seed(app)

    with app.app_context():
        result = create_edition_from_plan(_plan(league_id, player_ids))
        divisions = sorted(
            Edition.query.get(result["edition_id"]).divisions, key=lambda d: -d.rating
        )
        assert [d.rating for d in divisions] == [2000, 1000]
        for division in divisions:
            assert division.beginning_datetime.isoformat() == START
            assert division.end_date.isoformat() == "2026-10-27"
            assert division.has_ended is False


def test_rejects_division_with_wrong_player_count(app):
    league_id, player_ids = _seed(app)
    plan = _plan(league_id, player_ids)
    plan["divisions"][1]["players"] = player_ids[8:15]

    with app.app_context():
        with pytest.raises(EditionPlanError, match="expected 8 players, got 7"):
            create_edition_from_plan(plan)


def test_rejects_player_in_two_divisions(app):
    league_id, player_ids = _seed(app)
    plan = _plan(league_id, player_ids)
    plan["divisions"][1]["players"][0] = player_ids[0]

    with app.app_context():
        with pytest.raises(EditionPlanError, match="is in both"):
            create_edition_from_plan(plan)


def test_rejects_unknown_player(app):
    league_id, player_ids = _seed(app)
    plan = _plan(league_id, player_ids)
    plan["divisions"][0]["players"][0] = 999999

    with app.app_context():
        with pytest.raises(EditionPlanError, match="player\\(s\\) not found"):
            create_edition_from_plan(plan)


def test_rejects_duplicate_edition_name(app):
    league_id, player_ids = _seed(app)

    with app.app_context():
        create_edition_from_plan(_plan(league_id, player_ids))

    with app.app_context():
        with pytest.raises(EditionPlanError, match="already exists"):
            create_edition_from_plan(_plan(league_id, player_ids))


def test_rejects_division_name_already_used_by_another_edition(app):
    league_id, player_ids = _seed(app)

    with app.app_context():
        create_edition_from_plan(_plan(league_id, player_ids, divisions=1))

    plan = _plan(league_id, player_ids, divisions=1)
    plan["edition_name"] = "23ª Edição"
    with app.app_context():
        with pytest.raises(EditionPlanError, match="division names are unique"):
            create_edition_from_plan(plan)


def test_nothing_is_written_when_a_later_division_is_invalid(app):
    league_id, player_ids = _seed(app)
    plan = _plan(league_id, player_ids)
    plan["divisions"][1]["players"] = player_ids[8:15]  # only 7

    with app.app_context():
        with pytest.raises(EditionPlanError):
            create_edition_from_plan(plan)

    with app.app_context():
        assert Edition.query.count() == 0
        assert Division.query.count() == 0
        assert Match.query.count() == 0
        assert Association_PlayerDivision.query.count() == 0


def test_validate_plan_writes_nothing(app):
    league_id, player_ids = _seed(app)

    with app.app_context():
        validated = validate_plan(_plan(league_id, player_ids))
        assert validated["edition_name"] == "22ª Edição"
        assert len(validated["divisions"]) == 2

    with app.app_context():
        assert Edition.query.count() == 0
        assert Division.query.count() == 0
