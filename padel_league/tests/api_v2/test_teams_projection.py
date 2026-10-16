from padel_league.models import Player
from padel_league.models.v2 import CompetitionGroup, GroupMember
from padel_league.services import teams_divisions, teams_pairing
from padel_league.sql_db import db
from padel_league.tests.api_v2.conftest import bearer, check, persist
from padel_league.tests.api_v2.test_auth_teams import TEAMS, _open_pairing

PROJECTION = "/competitions/{competitionId}/teams/projection"
SIMULATE = "/competitions/{competitionId}/teams/simulate"


def _projection(client):
    return check(client.get(f"/api/v2/competitions/{TEAMS}/teams/projection"), PROJECTION)


def _ranked(body):
    """Roster player ids by ranking order, from the projection's own refs."""
    players = [pl for d in body["divisions"] for p in d["pairs"] for pl in p["players"]]
    return [pl["id"] for pl in sorted(players, key=lambda pl: (pl["rankingPosition"] or 10**9, pl["id"]))]


def test_projection_board(client):
    _open_pairing()
    body = _projection(client)
    assert body["counts"] == {"players": 48, "pairsTotal": 24, "pairsConfirmed": 0, "unpaired": 48, "pendingDeclarations": 0}
    assert body["stage"]["pairingOpen"] and not body["stage"]["pairingClosed"]
    assert [d["tier"] for d in body["divisions"]] == [1, 2, 3, 4, 5, 6]
    assert [d["rating"] for d in body["divisions"]] == [500, 250, 125, 63, 31, 16]
    first = body["divisions"][0]
    assert first["maxPlacePoints"] == 500 and first["maxBonusPoints"] == 45.0
    assert [p["seed"] for p in first["pairs"]] == [1, 2, 3, 4]
    assert first["minSum"] == min(p["sum"] for p in first["pairs"]) and first["maxSum"] == max(p["sum"] for p in first["pairs"])
    # Nobody chose yet: everyone is paired by ranking, 1.º+2.º, 3.º+4.º, …
    pairs = [p for d in body["divisions"] for p in d["pairs"]]
    assert all(p["provisional"] and p["formedBy"] == "ranking" and p["pairId"] is None for p in pairs)
    assert first["pairs"][0]["unpairedSlots"] == [1, 2]
    check(client.get("/api/v2/competitions/25/teams/projection"), PROJECTION, status=404)


def test_projection_shows_pending_and_mutual(client, make_user):
    stage = _open_pairing()
    first = _projection(client)
    a, b, c = _ranked(first)[:3]
    teams_pairing.declare(stage, a, c)  # one-sided: a declared c
    persist()
    body = _projection(client)
    assert body["counts"]["pendingDeclarations"] == 1
    assert [(d["from"]["id"], d["to"]["id"]) for d in body["pending"]] == [(a, c)]
    holders = [p for d in body["divisions"] for p in d["pairs"] if p["pending"]]
    assert holders and all({a, c} & {pl["id"] for pl in p["players"]} for p in holders)
    teams_pairing.declare(stage, c, a)  # mutual: the pair is formed
    persist()
    body = _projection(client)
    assert body["counts"]["pairsConfirmed"] == 1 and body["counts"]["unpaired"] == 46 and not body["pending"]
    formed = next(p for d in body["divisions"] for p in d["pairs"] if {pl["id"] for pl in p["players"]} == {a, c})
    assert formed["formedBy"] == "mutual" and not formed["provisional"] and formed["pairId"]
    assert b in {pl["id"] for d in body["divisions"] for p in d["pairs"] for pl in p["players"]}


def test_projection_equals_close_and_build_divisions(client):
    """The board is what close() + build_divisions() would write, pair for pair and seed for seed."""
    stage = _open_pairing()
    ids = _ranked(_projection(client))
    teams_pairing.declare(stage, ids[0], ids[10])
    teams_pairing.declare(stage, ids[10], ids[0])
    teams_pairing.declare(stage, ids[5], ids[30])  # one-sided: ignored at close
    persist()
    projected = [
        (d["tier"], p["seed"], frozenset(pl["id"] for pl in p["players"]), p["sum"])
        for d in _projection(client)["divisions"]
        for p in d["pairs"]
    ]

    teams_pairing.close(stage)
    built = teams_divisions.build_divisions(stage)
    db.session.flush()
    actual = []
    for group, division in built:
        for seed, sp in enumerate(division, start=1):
            actual.append((group.tier, seed, frozenset(sp.players), sp.points))
    assert projected == actual
    seeds = {
        (g.tier, m.seed)
        for g in CompetitionGroup.query.filter_by(stage_id=stage.id)
        for m in GroupMember.query.filter_by(group_id=g.id)
    }
    assert seeds == {(t, s) for t, s, _, _ in projected}
    persist()
    after = _projection(client)  # closed: the board now reads the formed pairs
    assert after["stage"]["pairingClosed"] and after["counts"]["pairsConfirmed"] == 24
    assert [(d["tier"], p["seed"], frozenset(pl["id"] for pl in p["players"])) for d in after["divisions"] for p in d["pairs"]] == [
        (t, s, pl) for t, s, pl, _ in projected
    ]


def test_simulate(client, make_user):
    _open_pairing()
    ids = _ranked(_projection(client))
    me, partner = ids[0], ids[40]
    base = check(client.get(f"/api/v2/competitions/{TEAMS}/teams/simulate?player={me}"), SIMULATE)
    assert base["partner"] is None and base["locked"] is False
    assert base["baseline"]["partner"]["id"] == ids[1] and base["baseline"]["tier"] == 1
    assert base["result"]["tier"] == base["baseline"]["tier"] and base["result"]["partner"]["id"] == ids[1]
    assert len(base["candidates"]) == 47 and all(c["allowed"] for c in base["candidates"])

    body = check(client.get(f"/api/v2/competitions/{TEAMS}/teams/simulate?player={me}&partner={partner}"), SIMULATE)
    r = body["result"]
    assert body["partner"]["id"] == partner and r["partner"]["id"] == partner
    assert r["sum"] == sum(x["points"] for x in r["sumBreakdown"])
    mine = [p for d in body["divisions"] for p in d["pairs"] if p["mine"]]
    assert len(mine) == 1 and {pl["id"] for pl in mine[0]["players"]} == {me, partner} and mine[0]["formedBy"] == "extra"
    tiers = {d["tier"]: [p["sum"] for p in d["pairs"]] for d in body["divisions"]}
    assert r["gapUp"] == (min(tiers[r["tier"] - 1]) - r["sum"] if r["tier"] > 1 else None)
    assert r["marginDown"] == (r["sum"] - max(tiers[r["tier"] + 1]) if r["tier"] < 6 else None)
    row = next(c for c in body["candidates"] if c["player"]["id"] == partner)
    assert (row["tier"], row["seed"]) == (r["tier"], r["seed"])
    assert row["delta"] == body["baseline"]["tier"] - r["tier"]

    # The caller's own player by default; a refused or missing player is a 400.
    user = make_user(player=Player.query.get(me))
    persist()
    mine_default = check(client.get(f"/api/v2/competitions/{TEAMS}/teams/simulate", headers=bearer(user)), SIMULATE)
    assert mine_default["player"]["id"] == me
    check(client.get(f"/api/v2/competitions/{TEAMS}/teams/simulate"), SIMULATE, status=400)
    resp = check(client.get(f"/api/v2/competitions/{TEAMS}/teams/simulate?player={me}&partner={me}"), SIMULATE, status=400)
    assert resp["code"] == "pairing_rule"


def test_simulate_locked_when_paired(client):
    stage = _open_pairing()
    ids = _ranked(_projection(client))
    teams_pairing.declare(stage, ids[0], ids[1])
    teams_pairing.declare(stage, ids[1], ids[0])
    persist()
    body = check(client.get(f"/api/v2/competitions/{TEAMS}/teams/simulate?player={ids[0]}"), SIMULATE)
    assert body["locked"] and not any(c["allowed"] for c in body["candidates"])
    assert body["baseline"]["partner"]["id"] == ids[1]
    row = next(c for c in body["candidates"] if c["player"]["id"] == ids[1])
    assert row["status"] == "confirmed" and row["pairedWith"]["id"] == ids[0]
