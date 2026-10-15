from padel_league.models.v2 import Entry
from padel_league.sql_db import db
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


def test_create_classica_then_fixtures(client, make_user):
    admin = bearer(make_user(role="admin"))
    resp = client.post("/api/v2/competitions", json=_body(startsOn="2026-11-03"), headers=admin)
    assert resp.status_code == 201, resp.get_json()
    comp = resp.get_json()
    assert comp["format"] == "classica" and comp["groupCount"] == 6 and comp["playerCount"] == 48
    # S5 creates the fixtures with the edition; regenerating without force is refused
    resp = client.post(f"/api/v2/competitions/{comp['id']}/fixtures", json={}, headers=admin)
    assert resp.status_code == 409 and resp.get_json() == {
        "code": "fixtures_exist",
        "error": "Os jogos desta fase já foram gerados.",
    }


def test_fixtures_for_a_group_without_matches(client, make_user):
    comp = f.competition(format="classica", name="Fixtures test")
    stg = f.stage(comp)
    grp = f.group(stg, name="Fixtures test - 1ª Divisão")
    for _ in range(8):
        f.member(grp, f.entry(comp, f.player()))
    persist()
    admin = bearer(make_user(role="admin"))
    body = client.post(f"/api/v2/competitions/{comp.id}/fixtures", json={"firstRoundDate": "2026-11-03"}, headers=admin).get_json()
    group_matches = client.get(f"/api/v2/groups/{grp.id}/matches").get_json()
    assert body["id"] == comp.id and len(group_matches) == 42  # 7 jornadas × 6 matches
    assert client.post("/api/v2/competitions/26/fixtures", json={}, headers=admin).status_code == 409


def test_preview_flags_a_plan_create_would_refuse(client, make_user):
    # the names of the 22ª's divisions already exist → S5's validation, shown as a note
    body = client.post(
        "/api/v2/competitions/preview", json=_body(name="Masters de Outono"), headers=bearer(make_user(role="admin"))
    ).get_json()
    assert any("não pode ser criado" in n for n in body["notes"])


def test_shuffle_rounds_guards(client, make_user):
    admin = bearer(make_user(role="admin"))
    assert client.post("/api/v2/competitions/26/rounds", headers=bearer(make_user())).status_code == 403
    resp = client.delete("/api/v2/competitions/25/rounds", headers=admin)
    assert resp.status_code == 409 and resp.get_json()["code"] == "not_shuffle"


def test_fixtures_refusals_are_portuguese(client, make_user):
    comp = f.competition(format="classica", name="Short group test")
    grp = f.group(f.stage(comp), name="Short group test - 1ª Divisão")
    for _ in range(7):
        f.member(grp, f.entry(comp, f.player()))
    persist()
    admin = bearer(make_user(role="admin"))
    body = client.post(f"/api/v2/competitions/{comp.id}/fixtures", json={"firstRoundDate": "2026-11-03"}, headers=admin).get_json()
    assert body["code"] == "wrong_player_count" and "precisa de 8 jogadores" in body["error"]
    f.member(grp, f.entry(comp, f.player()))
    persist()
    db.session.expire_all()  # the test shares the request's session: drop the cached member list
    body = client.post(f"/api/v2/competitions/{comp.id}/fixtures", json={}, headers=admin).get_json()
    assert body["code"] == "no_start_date"
