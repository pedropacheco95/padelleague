"""Teams pair formation: the pairing rules, then the API end to end.

The API tests run on a local Postgres copy of production with the Teams
migration applied (template database `teams_template`); they are skipped when
it is not there. Each test gets a fresh copy.
"""

import subprocess
from collections import Counter
from datetime import datetime, timedelta

import pytest
from flask_jwt_extended import create_access_token, create_refresh_token

from padel_league.services.teams_pairing import PairingError, allowed, auto_pairs

# --- rules ------------------------------------------------------------------


def test_auto_pairs_nearest_in_ranking():
    assert auto_pairs([1, 2, 3, 4, 5, 6], Counter()) == [(1, 2), (3, 4), (5, 6)]


def test_auto_pairs_skips_a_fourth_time_together():
    history = Counter({(1, 2): 3})
    assert auto_pairs([1, 2, 3, 4], history) == [(1, 3), (2, 4)]


def test_auto_pairs_backtracks_instead_of_stranding_the_last_two():
    # Greedy would give (1,2) then leave 3 and 4, who already played 3 together.
    history = Counter({(3, 4): 3})
    assert auto_pairs([1, 2, 3, 4], history) == [(1, 3), (2, 4)]


def test_three_times_together_is_still_allowed_before_that():
    assert allowed(1, 2, Counter({(1, 2): 2}))
    assert not allowed(2, 1, Counter({(1, 2): 3}))


def test_auto_pairs_refuses_an_odd_count():
    with pytest.raises(PairingError):
        auto_pairs([1, 2, 3], Counter())


# --- API --------------------------------------------------------------------

TEMPLATE = "teams_template"


def _psql(*args):
    return subprocess.run(["psql", "-h", "localhost", "-U", "postgres", "-Atc", *args], capture_output=True, text=True)


def _template_exists():
    out = _psql(f"select 1 from pg_database where datname='{TEMPLATE}'", "postgres")
    return out.stdout.strip() == "1"


@pytest.fixture
def app():
    if not _template_exists():
        pytest.skip(f"local template database {TEMPLATE} not found")
    name = "teams_pytest"
    subprocess.run(["dropdb", "-h", "localhost", "-U", "postgres", "--if-exists", name], check=True)
    subprocess.run(["createdb", "-h", "localhost", "-U", "postgres", "-T", TEMPLATE, name], check=True)

    from padel_league import create_app
    from padel_league.modules import chatbot_api

    chatbot_api.orchestrator_agent = chatbot_api.orchestrator_agent or object()
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"postgresql://postgres@localhost:5432/{name}",
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "SECRET_KEY": "test",
            "JWT_SECRET_KEY": "test-jwt-secret-of-at-least-32-bytes",
            "JWT_TOKEN_LOCATION": ["headers"],
            "JWT_HEADER_TYPE": "Bearer",
        }
    )
    yield app
    from padel_league.sql_db import db

    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    subprocess.run(["dropdb", "-h", "localhost", "-U", "postgres", "--if-exists", name])


def _roster_users(app, n):
    """(user_id, player_id) of the first n roster players that have a login."""
    from padel_league.models import User
    from padel_league.models.teams import TeamsPlayer

    with app.app_context():
        roster = {r.player_id for r in TeamsPlayer.query.all()}
        users = User.query.filter(User.player_id.in_(roster)).order_by(User.player_id).limit(n).all()
        return [(u.id, u.player_id) for u in users]


def _as(app, user_id):
    with app.app_context():
        return {"Authorization": f"Bearer {create_access_token(identity=str(user_id))}"}


def _admin(app):
    from padel_league.models import User

    with app.app_context():
        return _as(app, User.query.filter_by(super_admin=True).first().id)


def test_state_is_public_and_lists_the_roster(app):
    body = app.test_client().get("/api/v1/teams/").get_json()
    assert body["miniTournament"]["number"] == 1
    assert len(body["players"]) == 48
    assert body["pairs"] == []
    assert body["me"]["inRoster"] is False


def test_mutual_choice_makes_a_pair(app):
    client = app.test_client()
    (ua, pa), (ub, pb) = _roster_users(app, 2)

    first = client.post("/api/v1/teams/partner", json={"partnerId": pb}, headers=_as(app, ua)).get_json()
    assert first["pairs"] == []
    assert first["me"]["myChoice"] == pb

    seen_by_b = client.get("/api/v1/teams/", headers=_as(app, ub)).get_json()
    assert seen_by_b["me"]["choseMe"] == [pa]

    second = client.post("/api/v1/teams/partner", json={"partnerId": pa}, headers=_as(app, ub)).get_json()
    assert len(second["pairs"]) == 1
    assert {p["id"] for p in second["pairs"][0]["players"]} == {pa, pb}
    assert second["pairs"][0]["source"] == "mutual"


def test_a_paired_player_cannot_be_chosen(app):
    client = app.test_client()
    (ua, pa), (ub, pb), (uc, pc) = _roster_users(app, 3)
    client.post("/api/v1/teams/partner", json={"partnerId": pb}, headers=_as(app, ua))
    client.post("/api/v1/teams/partner", json={"partnerId": pa}, headers=_as(app, ub))
    response = client.post("/api/v1/teams/partner", json={"partnerId": pa}, headers=_as(app, uc))
    assert response.status_code == 400
    assert "parelha" in response.get_json()["error"]


def test_choices_need_a_login(app):
    assert app.test_client().post("/api/v1/teams/partner", json={"partnerId": 1}).status_code == 401


def test_choices_close_at_the_deadline(app):
    from padel_league.models.teams import TeamsMiniTournament
    from padel_league.sql_db import db

    with app.app_context():
        TeamsMiniTournament.query.first().pairing_deadline = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()
    (ua, _), (_, pb) = _roster_users(app, 2)
    response = app.test_client().post("/api/v1/teams/partner", json={"partnerId": pb}, headers=_as(app, ua))
    assert response.status_code == 400
    assert "prazo" in response.get_json()["error"]


def test_fourth_time_with_the_same_partner_is_refused(app):
    from padel_league.models.teams import TeamsMiniTournament, TeamsPair
    from padel_league.sql_db import db

    (ua, pa), (_, pb) = _roster_users(app, 2)
    with app.app_context():
        for number in (2, 3, 4):
            db.session.add(TeamsMiniTournament(number=number, pairing_deadline=datetime.utcnow() + timedelta(days=1)))
        db.session.flush()
        for mt in TeamsMiniTournament.query.filter(TeamsMiniTournament.number < 4):
            a, b = sorted((pa, pb))
            db.session.add(TeamsPair(mini_tournament_id=mt.id, player_a_id=a, player_b_id=b, source="admin"))
        db.session.commit()

    client = app.test_client()
    state = client.get("/api/v1/teams/", headers=_as(app, ua)).get_json()
    assert state["miniTournament"]["number"] == 4
    assert next(p for p in state["players"] if p["id"] == pb)["allowedForMe"] is False
    response = client.post("/api/v1/teams/partner", json={"partnerId": pb}, headers=_as(app, ua))
    assert response.status_code == 400


def test_close_pairs_everyone_left_by_ranking(app):
    client = app.test_client()
    (ua, pa), (ub, pb) = _roster_users(app, 2)
    client.post("/api/v1/teams/partner", json={"partnerId": pb}, headers=_as(app, ua))
    client.post("/api/v1/teams/partner", json={"partnerId": pa}, headers=_as(app, ub))

    assert client.post("/api/v1/teams/close_pairing", headers=_as(app, ua)).status_code == 403
    body = client.post("/api/v1/teams/close_pairing", headers=_admin(app)).get_json()

    assert len(body["pairs"]) == 24
    assert Counter(p["source"] for p in body["pairs"]) == {"mutual": 1, "auto": 23}
    assert body["miniTournament"]["pairingClosed"] is True
    # Auto pairs are consecutive in the ranking order of the players left.
    left = [p["id"] for p in body["players"] if p["id"] not in (pa, pb)]
    auto = [tuple(sorted(q["id"] for q in p["players"])) for p in body["pairs"] if p["source"] == "auto"]
    assert auto == [tuple(sorted(left[i : i + 2])) for i in range(0, len(left), 2)]


def test_refresh_token_renews_the_session(app):
    from padel_league.models import User

    with app.app_context():
        user = User.query.first()
        refresh = create_refresh_token(identity=str(user.id))
        access = create_access_token(identity=str(user.id))
    client = app.test_client()
    body = client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {refresh}"}).get_json()
    assert body["access_token"] and body["refresh_token"]
    # An access token is not a refresh token, and vice versa.
    assert client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {access}"}).status_code == 422
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh}"})
    assert me.status_code == 422


def _player_user(app):
    from padel_league.models import User
    from padel_league.sql_db import db

    with app.app_context():
        user = User.query.filter(User.player_id.isnot(None), User.super_admin.isnot(True)).order_by(User.id).first()
        code = user.new_code()
        db.session.commit()
        return user.id, user.player_id, code


def test_reset_code_signs_in_and_allows_a_new_password(app):
    from werkzeug.security import check_password_hash

    from padel_league.models import User

    user_id, player_id, code = _player_user(app)
    client = app.test_client()
    body = client.post(f"/api/v1/auth/verify_generated_code/{user_id}", json={"generated_code": code}).get_json()
    assert body["access_token"] and body["refresh_token"] and body["user"]["id"] == user_id

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    response = client.put(f"/api/v1/players/{player_id}", data={"password": "nova-password-1"}, headers=headers)
    assert response.status_code == 200, response.get_json()
    with app.app_context():
        assert check_password_hash(User.query.get(user_id).password, "nova-password-1")


def test_a_normal_login_still_needs_the_current_password(app):
    user_id, player_id, _ = _player_user(app)
    response = app.test_client().put(
        f"/api/v1/players/{player_id}", data={"password": "nova-password-1"}, headers=_as(app, user_id)
    )
    assert response.status_code == 400


def test_reset_code_dies_after_five_wrong_guesses(app):
    user_id, _, code = _player_user(app)
    client = app.test_client()
    wrong = 10000 if code != 10000 else 10001
    for _ in range(5):
        assert client.post(f"/api/v1/auth/verify_generated_code/{user_id}", json={"generated_code": wrong}).status_code == 400
    response = client.post(f"/api/v1/auth/verify_generated_code/{user_id}", json={"generated_code": code})
    assert response.status_code == 400
    assert "código novo" in response.get_json()["error"]


def test_admin_adds_and_removes_roster_players(app):
    from padel_league.models import Player
    from padel_league.models.teams import TeamsPlayer

    with app.app_context():
        roster = {r.player_id for r in TeamsPlayer.query.all()}
        outsider = Player.query.filter(~Player.id.in_(roster)).order_by(Player.id).first().id
        insider = sorted(roster)[0]
    client = app.test_client()
    added = client.post(f"/api/v1/teams/roster/{outsider}", headers=_admin(app)).get_json()
    assert len(added["players"]) == 49
    removed = client.delete(f"/api/v1/teams/roster/{insider}", headers=_admin(app)).get_json()
    assert len(removed["players"]) == 48
    assert insider not in {p["id"] for p in removed["players"]}
    assert client.post(f"/api/v1/teams/roster/{outsider}", headers=_as(app, _roster_users(app, 1)[0][0])).status_code == 403
