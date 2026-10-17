from padel_league.models import Player, User
from padel_league.sql_db import db
from padel_league.tests.api_v2.conftest import bearer, check, persist

LIST = "/admin/password-codes"
ONE = "/admin/password-codes/{userId}"


def _player(name):
    player = Player(name=name)
    db.session.add(player)
    persist()
    return player


def test_request_lists_for_admins_and_code_logs_in(client, make_user):
    admin = make_user(role="admin")
    player = _player("Pw Request")
    user = make_user(player=player, username="pw_request")

    first = client.post("/api/v1/auth/forgot_password", json={"username": "pw_request"})
    assert first.status_code == 200 and first.get_json() == {"user_id": user.id}
    code = User.query.get(user.id).generated_code
    assert code is not None
    # asking again keeps the code an admin may already have sent
    client.post("/api/v1/auth/forgot_password", json={"username": "pw_request"})
    client.post(f"/api/v1/auth/generate_new_code/{user.id}")
    assert User.query.get(user.id).generated_code == code

    listed = check(client.get("/api/v2" + LIST, headers=bearer(admin)), LIST)
    mine = [c for c in listed if c["userId"] == user.id]
    assert mine == [{"userId": user.id, "username": "pw_request", "player": mine[0]["player"], "code": f"{int(code):05d}"}]
    assert mine[0]["player"]["id"] == player.id

    body = client.post(f"/api/v1/auth/verify_generated_code/{user.id}", json={"generated_code": int(code)}).get_json()
    assert body["access_token"] and body["player_id"] == player.id
    assert user.id not in [c["userId"] for c in check(client.get("/api/v2" + LIST, headers=bearer(admin)), LIST)]


def test_admin_makes_and_dismisses_a_code(client, make_user):
    admin = make_user(role="admin")
    player = _player("Pw Admin")
    user = make_user(player=player, username="pw_admin")

    made = check(client.post("/api/v2" + LIST, json={"playerId": player.id}, headers=bearer(admin)), LIST, "post")
    assert made["userId"] == user.id and len(made["code"]) == 5
    again = check(client.post("/api/v2" + LIST, json={"playerId": player.id}, headers=bearer(admin)), LIST, "post")
    assert again["code"] == made["code"]

    check(client.delete(f"/api/v2/admin/password-codes/{user.id}", headers=bearer(admin)), ONE, "delete", 204)
    assert User.query.get(user.id).generated_code is None
    check(client.delete("/api/v2/admin/password-codes/999999", headers=bearer(admin)), ONE, "delete", 404)


def test_errors_and_permissions(client, make_user):
    admin = make_user(role="admin")
    player = make_user(role="player")
    no_account = _player("Pw No Account")

    check(client.get("/api/v2" + LIST), LIST, status=401)
    check(client.get("/api/v2" + LIST, headers=bearer(player)), LIST, status=403)
    check(client.post("/api/v2" + LIST, json={"playerId": no_account.id}, headers=bearer(player)), LIST, "post", 403)
    check(client.delete(f"/api/v2/admin/password-codes/{admin.id}", headers=bearer(player)), ONE, "delete", 403)
    check(client.post("/api/v2" + LIST, json={"playerId": no_account.id}, headers=bearer(admin)), LIST, "post", 404)
    check(client.post("/api/v2" + LIST, json={"playerId": 999999}, headers=bearer(admin)), LIST, "post", 404)
    check(client.post("/api/v2" + LIST, json={}, headers=bearer(admin)), LIST, "post", 400)
    assert client.post("/api/v1/auth/forgot_password", json={"username": "nobody_here"}).status_code == 404
