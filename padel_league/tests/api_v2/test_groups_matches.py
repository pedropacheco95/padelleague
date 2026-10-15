from padel_league.tests import factories as f
from padel_league.tests.api_v2.conftest import check, persist, stop_counting

TIER1_22 = 72  # 22ª Edição, Divisão 1, ended (frozen standings)


def test_frozen_group_page(client):
    body = check(client.get(f"/api/v2/groups/{TIER1_22}"), "/groups/{groupId}")
    assert body["standingsFrozen"] and body["hasEnded"]
    assert body["competition"]["id"] == 25 and body["tier"] == 1
    assert len(body["members"]) == len(body["standings"]) == 8
    assert [r["place"] for r in body["standings"]] == sorted(r["place"] for r in body["standings"])
    assert body["lastPlayedMatches"] and all(m["status"] == "played" for m in body["lastPlayedMatches"])
    assert body["standings"][0]["rankingPlacePoints"] is not None  # awards exist for closed groups


def test_group_page_query_count(client, count_queries):
    counter = count_queries()
    client.get(f"/api/v2/groups/{TIER1_22}")
    assert stop_counting(counter) <= 20


def test_group_matches(client, count_queries):
    counter = count_queries()
    body = check(client.get(f"/api/v2/groups/{TIER1_22}/matches"), "/groups/{groupId}/matches")
    assert stop_counting(counter) <= 12
    assert len(body) == 42
    m = body[0]
    assert len(m["participants"]) == 4 and len(m["sets"]) == 1
    assert m["homeScore"] == m["sets"][0]["homeGames"] and m["winner"] in ("home", "away", "draw")
    r3 = check(client.get(f"/api/v2/groups/{TIER1_22}/matches?round=3"), "/groups/{groupId}/matches")
    assert {x["round"] for x in r3} == {3} and any(x["absences"] for x in body)


def test_match_and_404(client):
    first = check(client.get(f"/api/v2/groups/{TIER1_22}/matches?round=1"), "/groups/{groupId}/matches")[0]
    body = check(client.get(f"/api/v2/matches/{first['id']}"), "/matches/{matchId}")
    assert body["id"] == first["id"] and body["competitionId"] == 25 and body["format"] == "classica"
    check(client.get("/api/v2/matches/99999999"), "/matches/{matchId}", status=404)
    check(client.get("/api/v2/groups/99999999"), "/groups/{groupId}", status=404)


def test_live_group_unknown_substitute_and_teams_score(client):
    comp = f.competition(format="teams", name="Teams test")
    stg = f.stage(comp)
    grp = f.group(stg)
    rnd = f.round_(stg)
    entries = [f.entry(comp, f.player()) for _ in range(4)]
    for e in entries:
        f.member(grp, e)
    m = f.match(grp, rnd, home=entries[:2], away=entries[2:3], status="played", sets=[(6, 3), (2, 6), (4, 4)])
    m.sets[2].outcome = "timeout_draw"
    persist()
    body = check(client.get(f"/api/v2/groups/{grp.id}"), "/groups/{groupId}")
    assert body["standingsFrozen"] is False and len(body["standings"]) == 4
    match = check(client.get(f"/api/v2/matches/{m.id}"), "/matches/{matchId}")
    assert match["participants"][3] == {"side": "away", "slot": 2, "role": "unknown", "player": None}
    assert (match["homeScore"], match["awayScore"], match["winner"]) == (3, 3, "draw")


def test_calendar(client):
    body = check(client.get("/api/v2/calendar?from=2026-09-01&to=2026-09-30&competition=25"), "/calendar")
    assert len(body) == 180 and all(m["scheduledAt"].startswith("2026-09") for m in body)
    one = check(client.get(f"/api/v2/calendar?from=2026-09-01&to=2026-09-01&group={TIER1_22}"), "/calendar")
    assert one and {m["groupId"] for m in one} == {TIER1_22}
    resp = client.get("/api/v2/calendar?from=2026-09-30&to=2026-09-01")
    assert resp.status_code == 400 and resp.get_json()["code"] == "invalid_parameter"
