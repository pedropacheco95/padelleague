from padel_league.models.v2 import RankingEntry
from padel_league.tests.api_v2.conftest import check, stop_counting


def _ranked_player_id():
    """The leader of the current (non-dry-run) ranking."""
    from padel_league.services.ranking import current_snapshot

    snap = current_snapshot()
    return (
        RankingEntry.query.filter(RankingEntry.snapshot_id == snap.id, RankingEntry.points > 0)
        .order_by(RankingEntry.points.desc())
        .first()
        .player_id
    )


def test_players_list(client, count_queries):
    counter = count_queries()
    body = check(client.get("/api/v2/players"), "/players")
    assert stop_counting(counter) <= 8  # constant, not per player
    ranked = [p for p in body if p["rankingPosition"] is not None]
    assert ranked and ranked[0]["rankingPosition"] == 1 and ranked[0]["id"] == _ranked_player_id()
    assert [p["rankingPoints"] for p in ranked] == sorted((p["rankingPoints"] for p in ranked), reverse=True)
    assert {p["status"] for p in body} <= {"active", "inactive", "substitute"}


def test_player_page(client):
    pid = _ranked_player_id()
    body = check(client.get(f"/api/v2/players/{pid}"), "/players/{playerId}")
    assert body["id"] == pid and body["history"]
    st = body["stats"]
    assert st["matchesPlayed"] == st["matchesWon"] + st["matchesDrawn"] + st["matchesLost"]
    assert 0 <= st["attendance"] <= 100 and st["tournamentsPlayed"] >= 1
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
    from padel_league.services.ranking import current_snapshot

    snap = current_snapshot()
    body = check(client.get("/api/v2/rankings/current"), "/rankings/current")
    assert body["rule"]["name"].startswith("Últimas 3")  # Portuguese for S3
    assert body["snapshotId"] == snap.id and body["entries"][0]["player"]["id"] == _ranked_player_id()
    points = [e["points"] for e in body["entries"]]
    assert points == sorted(points, reverse=True) and all(p > 0 for p in points)
    assert body["computedAt"].endswith("Z")
    check(client.get(f"/api/v2/rankings/{snap.id}"), "/rankings/{snapshotId}")
    resp = client.get("/api/v2/rankings/99999999")
    assert resp.status_code == 404


def test_ranking_explanation(client):
    pid = _ranked_player_id()
    resp = client.get(f"/api/v2/rankings/players/{pid}")
    if resp.status_code == 409:  # until the ranking bootstrap closes Shuffle 26 (S1)
        assert resp.get_json()["code"] == "ranking_missing_awards"
        return
    body = check(resp, "/rankings/players/{playerId}")
    assert body["player"]["id"] == pid and isinstance(body["lines"], list)


def test_unranked_players_have_null_position(client):
    body = check(client.get("/api/v2/players"), "/players")
    assert all((p["rankingPosition"] is None) == (p["rankingPoints"] == 0) for p in body)


def test_player_page_query_count(client, count_queries):
    pid = _ranked_player_id()
    counter = count_queries()
    client.get(f"/api/v2/players/{pid}")
    assert stop_counting(counter) <= 25


def test_upcoming_competition_shows_no_results(client):
    """Regression: a Teams entry with no group used to pick up an unrelated legacy
    snapshot (group_member_id NULL) — player 45 showed place 6, 21 wins in Teams 2026/27."""
    body = check(client.get("/api/v2/players/45"), "/players/{playerId}")
    teams = [h for h in body["history"] if h["competition"]["status"] == "upcoming"]
    assert teams, "player 45 is on the Teams 2026/27 roster"
    for row in teams:
        assert row["groupId"] is None
        assert all(row[k] is None for k in ("place", "points", "played", "wins", "draws", "losses", "awardPoints"))


def test_history_played_is_matches_not_jornadas(client):
    """S6 gate 2: player history counts matches (v1 tournamentHistory.played); only the
    group standings convert to jornadas. Player 10 in group 11: 21 matches = 7 jornadas."""
    body = check(client.get("/api/v2/players/10"), "/players/{playerId}")
    row = next(h for h in body["history"] if h["groupId"] == 11)
    assert row["played"] == 21
    group = check(client.get("/api/v2/groups/11"), "/groups/{groupId}")
    assert next(r for r in group["standings"] if r["player"]["id"] == 10)["played"] == 7


def _sub_setup():
    """A member who also played once as a substitute in another group, and an outside sub."""
    from padel_league.models.v2 import MatchParticipant
    from padel_league.services.ranking import current_snapshot
    from padel_league.sql_db import db
    from padel_league.tests import factories as f
    from padel_league.tests.api_v2.conftest import persist

    comp = f.competition(name="Subs test")
    stg = f.stage(comp)
    rnd = f.round_(stg)
    me, *others = [f.player() for _ in range(8)]
    g1, g2 = f.group(stg, tier=1, name="Subs test - 1ª Divisão"), f.group(stg, tier=2, name="Subs test - 2ª Divisão")
    ents = [f.entry(comp, p) for p in [me, *others]]
    for i, e in enumerate(ents):
        f.member(g1 if i < 4 else g2, e)
    f.match(g1, rnd, home=ents[0:2], away=ents[2:4], sets=[(6, 2)], status="played")  # me: won as a member
    # me subs for ents[4] in group 2 and loses
    sub = f.match(g2, rnd, home=ents[5:6], away=ents[6:8], sets=[(1, 6)], status="played")
    db.session.add(MatchParticipant(match_id=sub.id, side="home", slot=2, role="substitute", player_id=me.id))
    outsider = f.player(status="external")
    db.session.add(RankingEntry(snapshot_id=current_snapshot().id, player_id=outsider.id, points=99999, position=None))
    persist()
    return me.id, sub.id, outsider.id


def test_sub_appearances_counted_apart(client):
    """S0: stats count the player's own seats; sub appearances are subsMatches (v2 also lists them)."""
    me, sub_match, _ = _sub_setup()
    body = check(client.get(f"/api/v2/players/{me}"), "/players/{playerId}")
    st = body["stats"]
    assert (st["matchesPlayed"], st["matchesWon"], st["matchesLost"], st["subsMatches"]) == (1, 1, 0, 1)
    assert st["attendance"] == 100.0
    assert [m["id"] for m in body["substituteMatches"]] == [sub_match]
    seat = next(p for p in body["substituteMatches"][0]["participants"] if p["player"] and p["player"]["id"] == me)
    assert seat["role"] == "substitute"
    v1 = client.get(f"/api/v1/players/{me}").get_json()
    assert (v1["matchesPlayed"], v1["matchesWon"], v1["matchesLost"], v1["subsMatches"]) == (1, 1, 0, 1)
    assert [(h["played"], h["won"]) for h in v1["tournamentHistory"]] == [(1, 1)]


def test_external_players_hidden_from_lists_and_ranking(client):
    _, _, outsider = _sub_setup()
    assert outsider not in {p["id"] for p in check(client.get("/api/v2/players"), "/players")}
    ranking = check(client.get("/api/v2/rankings/current"), "/rankings/current")
    assert outsider not in {e["player"]["id"] for e in ranking["entries"]}
    for path in ("/api/v1/players/all", "/api/v1/players/short/all", "/api/v1/players/ranking"):
        assert outsider not in {p["id"] for p in client.get(path).get_json()}, path
    check(client.get(f"/api/v2/players/{outsider}"), "/players/{playerId}")
    assert client.get(f"/api/v1/players/{outsider}").status_code == 200
