from padel_league.models.v2 import Absence, GroupMember
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
    shuffle = check(client.get("/api/v2/competitions/26/standings"), "/competitions/{competitionId}/standings")
    assert shuffle and [r["place"] for r in shuffle] == sorted(r["place"] for r in shuffle)
    teams = check(client.get("/api/v2/competitions/27/standings"), "/competitions/{competitionId}/standings")
    assert len(teams) == 48 and all(r["points"] == 0 for r in teams)  # nothing played yet
    resp = client.get("/api/v2/competitions/25/standings")  # Clássica: per group only
    assert resp.status_code == 404 and resp.get_json()["code"] == "no_competition_standings"

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


def test_closed_group_is_admin_only(client, make_user):
    grp, (rnd,), entries, (m,) = _classica_group()
    grp.has_ended = True
    persist()
    payload = {"sets": [{"homeGames": 6, "awayGames": 2, "outcome": "completed"}]}
    resp = client.put(f"/api/v2/matches/{m.id}/result", json=payload, headers=bearer(make_user()))
    assert resp.status_code == 409 and resp.get_json()["code"] == "group_closed"
    resp = client.post(f"/api/v2/rounds/{rnd.id}/absences", json={"playerId": entries[0].player_id, "groupId": grp.id}, headers=bearer(make_user()))
    assert resp.status_code == 409 and resp.get_json()["code"] == "group_closed"
    resp = client.put(f"/api/v2/matches/{m.id}/result", json=payload, headers=bearer(make_user(role="admin")))
    assert resp.status_code == 200


def test_teams_standings_stage_lines_after_close(client):
    """S4: a closed mini-tournament's line carries the ranking points awarded (and the set points)."""
    from datetime import datetime

    from padel_league.models.v2 import Award, AwardEvent

    comp = f.competition(format="teams", name="Teams stage-lines test")
    stg = f.stage(comp, emits_award=True)
    grp = f.group(stg, rating=500)
    rnd = f.round_(stg)
    entries = [f.entry(comp, f.player()) for _ in range(4)]
    for e in entries:
        f.member(grp, e)
    f.match(grp, rnd, home=entries[:2], away=entries[2:], status="played", sets=[(6, 2), (6, 3), (1, 6)])
    grp.has_ended = True
    event = AwardEvent(competition_id=comp.id, stage_id=stg.id, group_id=grp.id, awarded_at=datetime.utcnow())
    db.session.add(event)
    db.session.flush()
    for place, e in enumerate(entries, 1):
        db.session.add(Award(award_event_id=event.id, entry_id=e.id, player_id=e.player_id, group_id=grp.id,
                             place=place, place_points=500.0 / place, bonus_points=1.5))
    persist()
    rows = check(client.get(f"/api/v2/competitions/{comp.id}/standings"), "/competitions/{competitionId}/standings")
    top = next(r for r in rows if r["player"]["id"] == entries[0].player_id)
    (line,) = top["stages"]
    assert line["groupId"] == grp.id and line["points"] == 501.5 and top["points"] == 501.5
    assert line["setPoints"] == 6  # two sets won × 3


def test_partial_absence_shows_only_on_missed_matches(client, make_user):
    comp = f.competition(format="classica", name="Partial test")
    stg = f.stage(comp)
    grp = f.group(stg)
    rnd = f.round_(stg)
    entries = [f.entry(comp, f.player()) for _ in range(4)]
    for e in entries:
        f.member(grp, e)
    m1 = f.match(grp, rnd, home=entries[:2], away=entries[2:])
    m2 = f.match(grp, rnd, home=[entries[0], entries[2]], away=[entries[1], entries[3]])
    persist()
    absent = entries[0].player_id
    resp = client.post(
        f"/api/v2/rounds/{rnd.id}/absences",
        json={"playerId": absent, "groupId": grp.id, "kind": "partial", "matchIds": [m1.id]},
        headers=bearer(make_user()),
    )
    assert resp.status_code == 201 and resp.get_json()["kind"] == "partial"
    missed = client.get(f"/api/v2/matches/{m1.id}").get_json()
    played = client.get(f"/api/v2/matches/{m2.id}").get_json()
    assert [a["player"]["id"] for a in missed["absences"]] == [absent]
    assert played["absences"] == []
    resp = client.post(
        f"/api/v2/rounds/{rnd.id}/absences", json={"playerId": absent, "groupId": grp.id, "kind": "partial"},
        headers=bearer(make_user()),
    )
    assert resp.status_code == 400 and resp.get_json()["code"] == "match_ids_required"


def test_clear_result(client, make_user):
    grp, _, _, (m, _m2) = _classica_group(n_rounds=2)  # one result left open, so the group stays open
    path = "/matches/{matchId}/result"
    h = bearer(make_user())
    check(client.delete(f"/api/v2/matches/{m.id}/result"), path, "delete", 401)
    client.put(f"/api/v2/matches/{m.id}/result", json={"sets": [{"homeGames": 6, "awayGames": 4, "outcome": "completed"}]}, headers=h)
    body = check(client.delete(f"/api/v2/matches/{m.id}/result", headers=h), path, "delete")
    assert (body["status"], body["sets"], body["homeScore"]) == ("scheduled", [], None)
    grp.has_ended = True
    persist()
    resp = client.delete(f"/api/v2/matches/{m.id}/result", headers=h)
    assert resp.status_code == 409 and resp.get_json()["code"] == "group_closed"


def test_substitutes_list_and_create(client, make_user):
    path = "/substitutes"
    check(client.get("/api/v2/substitutes"), path, "get", 401)
    check(client.post("/api/v2/substitutes", json={"name": "Zé Fora"}, headers=bearer(make_user())), path, "post", 403)
    admin = bearer(make_user(role="admin"))
    check(client.post("/api/v2/substitutes", json={"name": "  "}, headers=admin), path, "post", 400)
    made = check(client.post("/api/v2/substitutes", json={"name": "Zé  Fora"}, headers=admin), path, "post", 201)
    assert made["name"] == "Zé Fora"
    again = check(client.post("/api/v2/substitutes", json={"name": "zé fora"}, headers=admin), path, "post", 200)
    assert again["id"] == made["id"]
    listed = check(client.get("/api/v2/substitutes", headers=admin), path, "get")
    assert made["id"] in [p["id"] for p in listed]
    member = f.player()
    persist()
    reused = check(client.post("/api/v2/substitutes", json={"name": member.name}, headers=admin), path, "post", 200)
    assert reused["id"] == member.id


def test_last_teams_result_closes_the_group_itself(client, make_user):
    """Pedro, 30 Oct: "Fechar grupo" should not exist, the group closes once the last result is saved.
    This pins that: the last PUT /matches/{id}/result of a Teams group freezes it (status, standings
    snapshot, awards, ranking) and leaves POST /groups/{id}/close with nothing to do (409)."""
    from padel_league.models.v2 import AwardEvent, RankingSnapshot, StandingSnapshot

    comp = f.competition(format="teams", name="Teams auto-close test")
    stg = f.stage(comp, emits_award=True)
    grp = f.group(stg, rating=500)
    rounds = [f.round_(stg, number=i + 1) for i in range(2)]
    entries = [f.entry(comp, f.player()) for _ in range(4)]
    for e in entries:
        f.member(grp, e)
    m1 = f.match(grp, rounds[0], home=entries[:2], away=entries[2:])
    m2 = f.match(grp, rounds[1], home=[entries[0], entries[2]], away=[entries[1], entries[3]])
    persist()
    h = bearer(make_user())
    sets = [{"homeGames": 6, "awayGames": 2, "outcome": "completed"}, {"homeGames": 6, "awayGames": 3, "outcome": "completed"}, {"homeGames": 1, "awayGames": 6, "outcome": "completed"}]
    before = RankingSnapshot.query.count()

    check(client.put(f"/api/v2/matches/{m1.id}/result", json={"sets": sets}, headers=h), "/matches/{matchId}/result", "put")
    db.session.expire_all()
    assert not grp.has_ended and stg.status != "ended"  # one match still to play

    check(client.put(f"/api/v2/matches/{m2.id}/result", json={"sets": sets}, headers=h), "/matches/{matchId}/result", "put")
    db.session.expire_all()
    assert grp.has_ended and grp.standings_up_to_date and grp.end_date is not None
    assert stg.status == "ended" and comp.status == "ended"
    event = AwardEvent.query.filter_by(group_id=grp.id).one()
    # entries[0] won both, entries[3] lost both, the other two split: shared 2nd
    assert sorted(a.place for a in event.awards) == [1, 2, 2, 4] and all(a.rating == 500 for a in event.awards)
    assert StandingSnapshot.query.join(GroupMember, GroupMember.id == StandingSnapshot.group_member_id).filter(GroupMember.group_id == grp.id).count() == 4
    assert RankingSnapshot.query.count() == before + 1
    assert check(client.get(f"/api/v2/groups/{grp.id}"), "/groups/{groupId}")["hasEnded"] is True
    resp = client.post(f"/api/v2/groups/{grp.id}/close", headers=bearer(make_user(role="admin")))
    assert resp.status_code == 409 and resp.get_json()["code"] == "group_already_closed"
