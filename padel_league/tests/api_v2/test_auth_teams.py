from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from padel_league.models import Player
from padel_league.models.v2 import Entry, Stage
from padel_league.sql_db import db
from padel_league.tests.api_v2.conftest import bearer, check, persist

TEAMS = 27


def test_login_refresh_me(client, make_user):
    user = make_user(role="admin", username="v2_login")
    user.password = generate_password_hash("pw")
    persist()
    body = check(client.post("/api/v2/auth/login", json={"username": "v2_login", "password": "pw"}), "/auth/login", "post")
    assert body["user"]["role"] == "admin" and body["user"]["isAdmin"] and not body["user"]["superAdmin"]
    check(client.post("/api/v2/auth/login", json={"username": "v2_login", "password": "no"}), "/auth/login", "post", 401)
    refreshed = check(client.post("/api/v2/auth/refresh", headers={"Authorization": f"Bearer {body['refresh_token']}"}), "/auth/refresh", "post")
    assert refreshed["access_token"]
    # an access token is not a refresh token, and vice versa
    check(client.post("/api/v2/auth/refresh", headers={"Authorization": f"Bearer {body['access_token']}"}), "/auth/refresh", "post", 401)
    check(client.get("/api/v2/auth/me", headers={"Authorization": f"Bearer {body['refresh_token']}"}), "/auth/me", status=401)
    me = check(client.get("/api/v2/auth/me", headers=bearer(user)), "/auth/me")
    assert me["user"]["id"] == user.id
    check(client.get("/api/v2/auth/me"), "/auth/me", status=401)
    check(client.get("/api/v2/auth/me", headers={"Authorization": "Bearer garbage"}), "/auth/me", status=401)


def _open_pairing():
    stage = Stage.query.filter_by(competition_id=TEAMS, number=1).one()
    stage.pairing_deadline = datetime.utcnow() + timedelta(days=2)
    stage.pairing_closed = False
    persist()
    return stage


def _roster_players(n=2):
    entries = Entry.query.filter_by(competition_id=TEAMS, status="active").order_by(Entry.id).limit(n).all()
    return [Player.query.get(e.player_id) for e in entries]


def test_teams_state_anonymous(client):
    _open_pairing()
    body = check(client.get(f"/api/v2/competitions/{TEAMS}/teams"), "/competitions/{competitionId}/teams")
    assert len(body["players"]) == 48 and body["miniTournament"]["pairingOpen"]
    assert body["me"]["playerId"] is None and body["me"]["isAdmin"] is False


def test_mutual_choice_pairs(client, make_user):
    _open_pairing()
    a, b = _roster_players()
    ua, ub = make_user(player=a), make_user(player=b)
    path = "/competitions/{competitionId}/partner-requests"
    body = check(client.post(f"/api/v2/competitions/{TEAMS}/partner-requests", json={"partnerId": b.id}, headers=bearer(ua)), path, "post")
    assert body["me"]["myChoice"] == b.id
    body = check(client.post(f"/api/v2/competitions/{TEAMS}/partner-requests", json={"partnerId": a.id}, headers=bearer(ub)), path, "post")
    assert body["me"]["pairId"] is not None
    pair = next(p for p in body["pairs"] if p["id"] == body["me"]["pairId"])
    assert pair["source"] == "mutual" and {p["id"] for p in pair["players"]} == {a.id, b.id}


def test_partner_request_errors(client, make_user):
    _open_pairing()
    path = "/competitions/{competitionId}/partner-requests"
    check(client.post(f"/api/v2/competitions/{TEAMS}/partner-requests", json={"partnerId": 1}), path, "post", 401)
    outsider = make_user()
    check(client.post(f"/api/v2/competitions/{TEAMS}/partner-requests", json={"partnerId": 1}, headers=bearer(outsider)), path, "post", 400)
    check(client.post(f"/api/v2/competitions/{TEAMS}/partner-requests", json={}, headers=bearer(outsider)), path, "post", 400)


def test_admin_guards(client, make_user):
    _open_pairing()
    a, b = _roster_players()
    path = "/competitions/{competitionId}/pairs"
    check(client.post(f"/api/v2/competitions/{TEAMS}/pairs", json={"playerIds": [a.id, b.id]}, headers=bearer(make_user())), path, "post", 403)
    body = check(client.post(f"/api/v2/competitions/{TEAMS}/pairs", json={"playerIds": [a.id, b.id]}, headers=bearer(make_user(role="admin"))), path, "post")
    pair = body["pairs"][0]
    assert pair["source"] == "admin" and body["me"]["isAdmin"]
    body = check(
        client.delete(f"/api/v2/competitions/{TEAMS}/pairs/{pair['id']}", headers=bearer(make_user(role="super_admin"))),
        "/competitions/{competitionId}/pairs/{pairId}", "delete",
    )
    assert body["pairs"] == []


def test_teams_is_teams_only(client):
    resp = client.get("/api/v2/competitions/25/teams")
    assert resp.status_code == 404 and resp.get_json()["code"] == "not_teams"


def test_teams_state_query_count(client, count_queries):
    from padel_league.tests.api_v2.conftest import stop_counting

    counter = count_queries()
    client.get(f"/api/v2/competitions/{TEAMS}/teams")
    assert stop_counting(counter) <= 15


def test_teams_ranking_matches_the_current_snapshot(client):
    """D10: unranked players have no position; ranked ones match /players."""
    _open_pairing()
    teams = check(client.get(f"/api/v2/competitions/{TEAMS}/teams"), "/competitions/{competitionId}/teams")
    listing = {p["id"]: p for p in check(client.get("/api/v2/players"), "/players")}
    for p in teams["players"]:
        assert p["rankingPosition"] == (listing[p["id"]]["rankingPosition"] or 0)
        assert p["rankingPoints"] == listing[p["id"]]["rankingPoints"]
