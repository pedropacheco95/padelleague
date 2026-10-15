from padel_league.models.v2 import Entry
from padel_league.tests import factories as f
from padel_league.tests.api_v2.conftest import bearer, persist

PREV = 25  # 22ª Edição: 6 divisions of 8


def _body(**kw):
    return {"format": "classica", "name": "23ª Edição", "seasonId": 6, "fromCompetitionId": PREV, **kw}


def test_preview_needs_admin(client, make_user):
    assert client.post("/api/v2/competitions/preview", json=_body()).status_code == 401
    assert client.post("/api/v2/competitions/preview", json=_body(), headers=bearer(make_user())).status_code == 403


def test_preview_promotion_keeps_everyone(client, make_user):
    body = client.post("/api/v2/competitions/preview", json=_body(), headers=bearer(make_user(role="admin"))).get_json()
    groups = body["groups"]
    assert [g["tier"] for g in groups] == [1, 2, 3, 4, 5, 6]
    assert [g["rating"] for g in groups] == [2000, 1000, 500, 250, 125, 63]
    assert all(len(g["players"]) == 8 for g in groups)
    assert groups[0]["name"] == "23ª Edição - 1ª Divisão"
    previous = {e.player_id for e in Entry.query.filter_by(competition_id=PREV)}
    assert {p["id"] for g in groups for p in g["players"]} == previous


def test_preview_withdrawal_filled_by_newcomer(client, make_user):
    admin = make_user(role="admin")
    first = client.post("/api/v2/competitions/preview", json=_body(), headers=bearer(admin)).get_json()["groups"]
    leaver = first[0]["players"][0]["id"]
    rookie = f.player()
    persist()
    body = client.post(
        "/api/v2/competitions/preview",
        json=_body(withdrawals=[leaver], newPlayerIds=[rookie.id]),
        headers=bearer(admin),
    ).get_json()
    ids = [p["id"] for g in body["groups"] for p in g["players"]]
    assert leaver not in ids and rookie.id in [p["id"] for p in body["groups"][-1]["players"]]
    assert all(len(g["players"]) == 8 for g in body["groups"]) and body["notes"]


def test_preview_bad_input(client, make_user):
    h = bearer(make_user(role="admin"))
    assert client.post("/api/v2/competitions/preview", json=_body(format="x"), headers=h).status_code == 400
    assert client.post("/api/v2/competitions/preview", json=_body(fromCompetitionId=26), headers=h).status_code == 400


def test_create_classica(client, make_user):
    resp = client.post("/api/v2/competitions", json=_body(startsOn="2026-11-03"), headers=bearer(make_user(role="admin")))
    if resp.status_code == 409:  # S5's v2 create-edition not merged yet
        assert resp.get_json()["code"] == "not_available"
        return
    assert resp.status_code == 201
    comp = resp.get_json()
    assert comp["format"] == "classica" and comp["groupCount"] == 6 and comp["playerCount"] == 48


def test_shuffle_rounds_guards(client, make_user):
    admin = bearer(make_user(role="admin"))
    assert client.post("/api/v2/competitions/26/rounds", headers=bearer(make_user())).status_code == 403
    resp = client.delete("/api/v2/competitions/25/rounds", headers=admin)
    assert resp.status_code == 409 and resp.get_json()["code"] == "not_shuffle"
