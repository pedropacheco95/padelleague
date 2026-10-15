from padel_league.models.v2 import Absence, CompetitionMatch
from padel_league.sql_db import db
from padel_league.tests import factories as f
from padel_league.tests.api_v2.conftest import bearer, check, persist


def _classica_group(n_rounds=1):
    comp = f.competition(format="classica", name="Write test")
    stg = f.stage(comp)
    grp = f.group(stg, rating=None)
    rounds = [f.round_(stg, number=i + 1) for i in range(n_rounds)]
    entries = [f.entry(comp, f.player()) for _ in range(4)]
    for e in entries:
        f.member(grp, e)
    matches = [f.match(grp, r, home=entries[:2], away=entries[2:]) for r in rounds]
    persist()
    return grp, rounds, entries, matches


def test_result_requires_login(client):
    _, _, _, (m,) = _classica_group()
    path = "/matches/{matchId}/result"
    check(client.put(f"/api/v2/matches/{m.id}/result", json={"sets": []}), path, "put", 401)


def test_record_classica_result(client, make_user):
    grp, _, _, (m, m2) = _classica_group(n_rounds=2)
    body = check(
        client.put(
            f"/api/v2/matches/{m.id}/result",
            json={"sets": [{"homeGames": 6, "awayGames": 4, "outcome": "completed"}], "court": "Campo 2"},
            headers=bearer(make_user()),
        ),
        "/matches/{matchId}/result", "put",
    )
    assert (body["status"], body["homeScore"], body["awayScore"], body["winner"], body["court"]) == ("played", 6, 4, "home", "Campo 2")


def test_bad_result_payloads(client, make_user):
    _, _, _, (m,) = _classica_group()
    h = bearer(make_user())
    path = "/matches/{matchId}/result"
    check(client.put(f"/api/v2/matches/{m.id}/result", json={"sets": [{"outcome": "nope"}]}, headers=h), path, "put", 400)
    check(client.put(f"/api/v2/matches/{m.id}/result", json={"sets": "x"}, headers=h), path, "put", 400)
    check(client.put(f"/api/v2/matches/{m.id}/result", json={"walkoverWinner": "left"}, headers=h), path, "put", 400)


def test_absence_with_substitute_then_delete(client, make_user):
    grp, (rnd,), entries, (m,) = _classica_group()
    sub = f.player()
    persist()
    h = bearer(make_user())
    absent = entries[0].player_id
    body = check(
        client.post(f"/api/v2/rounds/{rnd.id}/absences", json={"playerId": absent, "groupId": grp.id, "substitutePlayerId": sub.id}, headers=h),
        "/rounds/{roundId}/absences", "post", 201,
    )
    assert body["player"]["id"] == absent and body["substitute"]["id"] == sub.id and body["source"] == "recorded"
    match = check(client.get(f"/api/v2/matches/{m.id}"), "/matches/{matchId}")
    assert any(p["role"] == "substitute" and p["player"]["id"] == sub.id for p in match["participants"])
    resp = client.delete(f"/api/v2/absences/{body['id']}", headers=h)
    assert resp.status_code == 204 and db.session.get(Absence, body["id"]) is None
    match = check(client.get(f"/api/v2/matches/{m.id}"), "/matches/{matchId}")
    restored = {p["player"]["id"]: p["role"] for p in match["participants"] if p["player"]}
    assert restored.get(absent) == "member" and sub.id not in restored
    outsider = f.player()
    persist()
    check(client.post(f"/api/v2/rounds/{rnd.id}/absences", json={"playerId": outsider.id, "groupId": grp.id}, headers=h), "/rounds/{roundId}/absences", "post", 400)


def test_close_group_is_admin_and_needs_all_results(client, make_user):
    grp, _, _, (m,) = _classica_group()
    path = "/groups/{groupId}/close"
    check(client.post(f"/api/v2/groups/{grp.id}/close", headers=bearer(make_user())), path, "post", 403)
    resp = check(client.post(f"/api/v2/groups/{grp.id}/close", headers=bearer(make_user(role="admin"))), path, "post", 409)
    assert resp["code"] == "group_not_complete"


def test_competition_standings_endpoint(client):
    body = check(client.get("/api/v2/competitions/26/standings"), "/competitions/{competitionId}/standings")
    assert isinstance(body, list)


def test_derived_absence_is_not_deleted(client, make_user):
    derived = Absence.query.filter_by(source="derived").first()
    resp = client.delete(f"/api/v2/absences/{derived.id}", headers=bearer(make_user()))
    assert resp.status_code == 409 and resp.get_json()["code"] == "absence_not_recorded"


def test_close_fallback_refuses_other_formats(client, make_user):
    comp = f.competition(format="shuffle", name="Shuffle close test")
    grp = f.group(f.stage(comp))
    persist()
    resp = client.post(f"/api/v2/groups/{grp.id}/close", headers=bearer(make_user(role="admin")))
    assert resp.status_code == 409


def test_divisions_guards(client, make_user):
    from padel_league.models.v2 import Stage

    stage = Stage.query.filter_by(competition_id=27, number=1).one()
    path = "/stages/{stageId}/divisions"
    check(client.post(f"/api/v2/stages/{stage.id}/divisions", headers=bearer(make_user())), path, "post", 403)
    # pairing still open (S1: pairing_not_closed) or service not merged yet (not_available): both 409
    body = check(client.post(f"/api/v2/stages/{stage.id}/divisions", headers=bearer(make_user(role="admin"))), path, "post", 409)
    assert body["code"] in ("pairing_not_closed", "not_available")
    resp = client.post("/api/v2/stages/99999999/divisions", headers=bearer(make_user(role="admin")))
    assert resp.status_code == 404
