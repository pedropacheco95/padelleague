import itertools
import os
import tempfile
from collections import Counter
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from padel_league import create_app
from padel_league.modules import chatbot_api
from padel_league.models import (
    Association_PlayerDivision,
    Association_PlayerMatch,
    Division,
    Match,
    Player,
)
from padel_league.services.fixtures import (
    FixtureGenerationError,
    generate_division_fixtures,
)
from padel_league.sql_db import db, init_db

# Same SQLite workaround as test_division_standings.py: `players_in_match` and
# `players_in_division` declare an autoincrement `id` inside a composite
# primary key, which Postgres accepts (the `id` gets a sequence default) but
# SQLite's DDL compiler rejects. We disable the flag for DDL, and — because the
# service under test deliberately does not assign ids by hand — install a
# Python-side default so SQLite still gets a unique id per row.
_COMPOSITE_PK_TABLES_WITH_AUTOINCREMENT = [
    Association_PlayerMatch.__table__,
    Association_PlayerDivision.__table__,
]

START = datetime(2026, 9, 15, 21, 30)


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
            # create_app bypasses the Config class when given a test config,
            # so the JWT settings the API endpoints need have to be spelled out.
            "JWT_SECRET_KEY": "test-jwt-secret",
            "JWT_TOKEN_LOCATION": ["headers"],
            "JWT_HEADER_TYPE": "Bearer",
        }
    )

    # chatbot_api registers a `before_app_request` hook that builds the LLM
    # agents on the first request of *any* endpoint. Mark them as already
    # initialised so hitting an unrelated API route doesn't need an API key.
    chatbot_api.orchestrator_agent = chatbot_api.orchestrator_agent or object()

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
    for table, autoincrement in zip(
        _COMPOSITE_PK_TABLES_WITH_AUTOINCREMENT, original_autoincrement
    ):
        table.c.id.autoincrement = autoincrement


# SQLite will not auto-assign the composite-pk `id`, and the service under test
# deliberately leaves it to the database (Postgres has a sequence default), so
# fill it in on the way to the insert.
_assoc_ids = itertools.count(1)


@event.listens_for(Association_PlayerMatch, "before_insert", propagate=True)
@event.listens_for(Association_PlayerDivision, "before_insert", propagate=True)
def _assign_assoc_id(_mapper, _connection, target):
    if target.id is None:
        target.id = next(_assoc_ids)


_division_assoc_id = itertools.count(1)


def _make_division(app, player_count=8, beginning=START):
    """Create a division with `player_count` players and return (id, [player ids])."""
    with app.app_context():
        division = Division(
            name=f"Teste {next(_division_assoc_id)}ª Divisão",
            beginning_datetime=beginning,
            rating=2000,
        )
        db.session.add(division)
        db.session.flush()

        player_ids = []
        for i in range(player_count):
            player = Player(name=f"Jogador {i + 1}")
            db.session.add(player)
            db.session.flush()
            db.session.add(
                Association_PlayerDivision(
                    player_id=player.id, division_id=division.id, place=i + 1
                )
            )
            player_ids.append(player.id)

        db.session.commit()
        return division.id, player_ids


def _generate(app, division_id, **kwargs):
    with app.app_context():
        division = Division.query.get(division_id)
        return generate_division_fixtures(division, **kwargs)


def test_generates_seven_matchweeks_of_six_games(app):
    division_id, _ = _make_division(app)
    summary = _generate(app, division_id)

    assert summary["matches_created"] == 42

    with app.app_context():
        matches = Match.query.filter_by(division_id=division_id).all()
        assert len(matches) == 42
        per_matchweek = Counter(match.matchweek for match in matches)
        assert per_matchweek == {mw: 6 for mw in range(1, 8)}
        assert all(match.played is False for match in matches)


def test_every_match_has_two_home_and_two_away(app):
    division_id, _ = _make_division(app)
    _generate(app, division_id)

    with app.app_context():
        for match in Match.query.filter_by(division_id=division_id).all():
            teams = Counter(rel.team for rel in match.players_relations)
            assert teams == {"Home": 2, "Away": 2}, f"match {match.id}: {teams}"


def test_each_player_partners_every_other_exactly_once(app):
    division_id, player_ids = _make_division(app)
    _generate(app, division_id)

    with app.app_context():
        appearances = Counter()
        partnerships = Counter()
        for match in Match.query.filter_by(division_id=division_id).all():
            for team in ("Home", "Away"):
                pair = sorted(
                    rel.player_id for rel in match.players_relations if rel.team == team
                )
                partnerships[tuple(pair)] += 1
                appearances.update(pair)

        # 7 jornadas x 3 jogos each
        assert appearances == {player_id: 21 for player_id in player_ids}
        # 4 fixed pairs per jornada x 7 jornadas = all 28 unordered pairs, and
        # each pair plays the other three pairs once within its own jornada.
        assert len(partnerships) == 28
        assert set(partnerships.values()) == {3}


def test_dates_are_weekly_and_fields_alternate(app):
    division_id, _ = _make_division(app)
    _generate(app, division_id)

    with app.app_context():
        matches = (
            Match.query.filter_by(division_id=division_id)
            .order_by(Match.matchweek, Match.id)
            .all()
        )
        for match in matches:
            expected = START + timedelta(days=7 * (match.matchweek - 1))
            assert match.date_hour == expected

        for matchweek in range(1, 8):
            fields = [m.field for m in matches if m.matchweek == matchweek]
            assert fields == ["Campo 1", "Campo 2"] * 3


def test_end_date_is_the_last_matchweek_not_a_week_later(app):
    division_id, _ = _make_division(app)
    summary = _generate(app, division_id)

    expected = (START + timedelta(days=7 * 6)).date()
    assert summary["end_date"] == expected.isoformat()
    with app.app_context():
        assert Division.query.get(division_id).end_date == expected


def test_seats_map_every_player_exactly_once(app):
    division_id, player_ids = _make_division(app)
    summary = _generate(app, division_id)

    seats = summary["seats"]
    assert sorted(seats) == [f"Player {i}" for i in range(1, 9)]
    assert sorted(seats.values()) == sorted(player_ids)


@pytest.mark.parametrize("player_count", [0, 7, 9])
def test_refuses_wrong_player_count(app, player_count):
    division_id, _ = _make_division(app, player_count=player_count)
    with pytest.raises(FixtureGenerationError, match="exactly 8"):
        _generate(app, division_id)


def test_refuses_without_beginning_datetime(app):
    division_id, _ = _make_division(app, beginning=None)
    with pytest.raises(FixtureGenerationError, match="beginning_datetime"):
        _generate(app, division_id)


def test_refuses_to_overwrite_existing_matches(app):
    division_id, _ = _make_division(app)
    _generate(app, division_id)

    with pytest.raises(FixtureGenerationError, match="already has 42 matches"):
        _generate(app, division_id)


def test_force_regenerates_when_nothing_has_been_played(app):
    division_id, _ = _make_division(app)
    first = _generate(app, division_id)
    second = _generate(app, division_id, force=True)

    assert first["matches_created"] == 42
    assert second["matches_created"] == 42
    with app.app_context():
        # replaced, not appended
        assert Match.query.filter_by(division_id=division_id).count() == 42
        assert Association_PlayerMatch.query.count() == 42 * 4


def test_force_is_refused_once_a_match_has_been_played(app):
    division_id, _ = _make_division(app)
    _generate(app, division_id)

    with app.app_context():
        match = Match.query.filter_by(division_id=division_id).first()
        match.played = True
        db.session.commit()

    with pytest.raises(FixtureGenerationError, match="already been played"):
        _generate(app, division_id, force=True)

    with app.app_context():
        assert Match.query.filter_by(division_id=division_id).count() == 42


def _auth_header(app):
    from flask_jwt_extended import create_access_token

    with app.app_context():
        return {"Authorization": f"Bearer {create_access_token(identity='1')}"}


def test_endpoint_generates_fixtures_and_names_the_draw(app):
    division_id, player_ids = _make_division(app)

    response = app.test_client().post(
        f"/api/v1/divisions/{division_id}/generate_matches",
        json={},
        headers=_auth_header(app),
    )

    assert response.status_code == 201, response.get_data(as_text=True)
    body = response.get_json()
    assert body["matches_created"] == 42
    assert sorted(seat["id"] for seat in body["seats"].values()) == sorted(player_ids)
    assert all(seat["name"] for seat in body["seats"].values())

    with app.app_context():
        assert Match.query.filter_by(division_id=division_id).count() == 42


def test_endpoint_requires_authentication(app):
    division_id, _ = _make_division(app)

    response = app.test_client().post(
        f"/api/v1/divisions/{division_id}/generate_matches", json={}
    )

    assert response.status_code == 401
    with app.app_context():
        assert Match.query.filter_by(division_id=division_id).count() == 0


def test_endpoint_reports_a_conflict_instead_of_crashing(app):
    division_id, _ = _make_division(app)
    headers = _auth_header(app)
    client = app.test_client()

    client.post(
        f"/api/v1/divisions/{division_id}/generate_matches", json={}, headers=headers
    )
    response = client.post(
        f"/api/v1/divisions/{division_id}/generate_matches", json={}, headers=headers
    )

    assert response.status_code == 409
    assert "already has 42 matches" in response.get_json()["message"]
