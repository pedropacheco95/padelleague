from datetime import date

from padel_league.tests import factories as f
from padel_league.tests.api_v2.conftest import check, persist, stop_counting


def test_seasons(client):
    body = check(client.get("/api/v2/seasons"), "/seasons")
    assert [s["name"] for s in body if s["isCurrent"]] == ["2026/27"]


def test_cards_cover_every_format_current_season_first(client):
    body = check(client.get("/api/v2/competitions"), "/competitions")
    ids = [c["id"] for c in body]
    assert 14 not in ids  # empty edition is hidden
    assert {25, 26, 27} <= set(ids)
    assert body[0]["season"]["isCurrent"]
    teams = next(c for c in body if c["id"] == 27)
    assert teams["format"] == "teams" and teams["status"] == "upcoming"
    assert teams["playerCount"] == 48 and teams["groupCount"] == 0
    shuffle = next(c for c in body if c["id"] == 26)
    assert shuffle["status"] in ("live", "ended") and shuffle["groupCount"] == 6
    classica = next(c for c in body if c["id"] == 25)
    assert classica["groupCount"] == 6 and classica["coverImage"]["url"].startswith("http")
    assert classica["legacyEditionId"] == 25 and teams["legacyEditionId"] is None


def test_cards_filters(client):
    body = check(client.get("/api/v2/competitions?format=classica&season=6"), "/competitions")
    assert [c["id"] for c in body] == [25]
    live = f.competition(format="classica", name="Live filter test")
    f.group(f.stage(live))
    persist()
    body = check(client.get("/api/v2/competitions?status=live"), "/competitions")
    assert live.id in [c["id"] for c in body] and {c["status"] for c in body} == {"live"}
    resp = client.get("/api/v2/competitions?format=nope")
    assert resp.status_code == 400 and resp.get_json()["code"] == "invalid_parameter"


def test_cards_query_count_is_constant(client, count_queries):
    counter = count_queries()
    client.get("/api/v2/competitions")
    assert stop_counting(counter) <= 8


def test_current_by_format(client):
    assert check(client.get("/api/v2/competitions/current?format=teams"), "/competitions/current")["id"] == 27
    assert check(client.get("/api/v2/competitions/current?format=shuffle"), "/competitions/current")["id"] == 26  # live or last ended
    assert check(client.get("/api/v2/competitions/current?format=classica"), "/competitions/current")["id"] == 25
    check(client.get("/api/v2/competitions/current?format=super_cup"), "/competitions/current", status=404)


def test_competition_page(client):
    body = check(client.get("/api/v2/competitions/25"), "/competitions/{competitionId}")
    assert len(body["stages"]) == 1 and len(body["stages"][0]["groups"]) == 6
    assert body["currentStageId"] == body["stages"][0]["id"]
    teams = check(client.get("/api/v2/competitions/27"), "/competitions/{competitionId}")
    assert [s["number"] for s in teams["stages"]] == [1, 2, 3, 4]
    assert teams["stages"][0]["pairingDeadline"].endswith("Z")
    check(client.get("/api/v2/competitions/14"), "/competitions/{competitionId}", status=404)
    check(client.get("/api/v2/competitions/999999"), "/competitions/{competitionId}", status=404)


def test_new_competition_card(client):
    comp = f.competition(format="super_cup", name="Super Cup test", starts_on=date(2026, 11, 1))
    stg = f.stage(comp)
    f.group(stg)
    persist()
    body = check(client.get("/api/v2/competitions?format=super_cup"), "/competitions")
    assert body[0]["id"] == comp.id and body[0]["status"] == "live" and body[0]["formatLabel"] == "Super Cup"
