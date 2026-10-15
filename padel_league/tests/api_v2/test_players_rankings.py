from padel_league.models.v2 import RankingEntry, RankingSnapshot
from padel_league.tests.api_v2.conftest import check, persist, stop_counting


def _ranked_player_id():
    snap = RankingSnapshot.query.filter_by(is_dry_run=False).first()
    return RankingEntry.query.filter_by(snapshot_id=snap.id).first().player_id


def _give_points():
    """The template's snapshot is all zeros until S1 computes it; give it some order."""
    snap = RankingSnapshot.query.filter_by(is_dry_run=False).first()
    for i, e in enumerate(RankingEntry.query.filter_by(snapshot_id=snap.id).order_by(RankingEntry.player_id)):
        e.points, e.position = 1000.5 - i, i + 1
    persist()
    return snap


def test_players_list(client, count_queries):
    _give_points()
    counter = count_queries()
    body = check(client.get("/api/v2/players"), "/players")
    assert stop_counting(counter) <= 8  # constant, not per player
    assert body[0]["rankingPosition"] == 1 and body[0]["rankingPoints"] == 1000.5
    assert {p["status"] for p in body} <= {"active", "inactive", "substitute"}


def test_player_page(client):
    pid = _ranked_player_id()
    body = check(client.get(f"/api/v2/players/{pid}"), "/players/{playerId}")
    assert body["id"] == pid and body["history"]
    assert body["stats"]["played"] == body["stats"]["wins"] + body["stats"]["draws"] + body["stats"]["losses"]
    check(client.get("/api/v2/players/99999999"), "/players/{playerId}", status=404)


def test_player_matches(client):
    pid = _ranked_player_id()
    body = check(client.get(f"/api/v2/players/{pid}/matches?competition=25"), "/players/{playerId}/matches")
    assert all(m["competitionId"] == 25 for m in body)
    assert all(any(p["player"] and p["player"]["id"] == pid for p in m["participants"]) for m in body)


def test_compare(client):
    pid = _ranked_player_id()
    matches = check(client.get(f"/api/v2/players/{pid}/matches"), "/players/{playerId}/matches")
    other = next(p["player"]["id"] for p in matches[0]["participants"] if p["player"] and p["player"]["id"] != pid)
    body = check(client.get(f"/api/v2/players/compare?a={pid}&b={other}"), "/players/compare")
    assert body["headToHead"]["played"] + body["together"]["played"] >= 1
    assert body["matches"]
    resp = client.get("/api/v2/players/compare?a=1")
    assert resp.status_code == 400


def test_rankings(client):
    snap = _give_points()
    body = check(client.get("/api/v2/rankings/current"), "/rankings/current")
    assert body["snapshotId"] == snap.id and body["entries"][0]["points"] == 1000.5
    assert body["computedAt"].endswith("Z")
    check(client.get(f"/api/v2/rankings/{snap.id}"), "/rankings/{snapshotId}")
    resp = client.get("/api/v2/rankings/99999999")
    assert resp.status_code == 404


def test_ranking_explanation(client):
    pid = _ranked_player_id()
    body = check(client.get(f"/api/v2/rankings/players/{pid}"), "/rankings/players/{playerId}")
    assert body["player"]["id"] == pid and isinstance(body["lines"], list)


def test_player_page_query_count(client, count_queries):
    pid = _ranked_player_id()
    counter = count_queries()
    client.get(f"/api/v2/players/{pid}")
    assert stop_counting(counter) <= 25
