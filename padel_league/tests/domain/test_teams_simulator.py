"""Teams partner simulator: project() equals what close() + build_divisions()
then produce, on the real 2026/27 roster (template clone, rolled back)."""

from datetime import datetime

import pytest

from padel_league.models.v2 import CompetitionGroup, Entry, Pair, PartnerRequest, Stage
from padel_league.services import ranking, teams_divisions, teams_pairing
from padel_league.services.teams_pairing import PairingError
from padel_league.sql_db import db

NOW = datetime(2026, 10, 17, 12, 0)


def _stage():
    comp = teams_pairing.current_competition()
    if comp is None:
        pytest.skip("no Teams competition in template")
    stage = Stage.query.filter_by(competition_id=comp.id, number=1).one()
    stage.pairing_deadline = datetime(2026, 10, 18, 23, 0)
    stage.pairing_closed = False
    ranking.bootstrap()
    return stage


def _board(divisions):
    """[(tier, [(sorted players, points, seed)])] of a projection or of built groups."""
    out = []
    for item in divisions:
        if isinstance(item, teams_divisions.ProjectedDivision):
            out.append((item.tier, [(tuple(sorted(p.players)), p.points, p.seed) for p in item.pairs]))
        else:
            group, division = item
            out.append((group.tier, [(tuple(sorted(sp.players)), sp.points, i) for i, sp in enumerate(division, 1)]))
    return out


def _counts(stage):
    return (
        Pair.query.filter_by(stage_id=stage.id).count(),
        PartnerRequest.query.filter_by(stage_id=stage.id).count(),
        CompetitionGroup.query.filter_by(stage_id=stage.id).count(),
        bool(stage.pairing_closed),
    )


def _by_position(stage):
    positions = ranking.seeding(stage.competition.season.league_id)[1]
    return sorted(teams_pairing.roster_ids(stage), key=lambda p: (positions.get(p) or 10**9, p))


def test_projection_equals_close_and_build(pg):
    stage = _stage()
    order = _by_position(stage)
    # one mutual pair already formed, one mutual choice that both requests missed
    teams_pairing.declare(stage, order[0], order[5], now=NOW)
    teams_pairing.declare(stage, order[5], order[0], now=NOW)
    db.session.add_all([
        PartnerRequest(stage_id=stage.id, from_entry_id=_entry(stage, order[10]).id, to_entry_id=_entry(stage, order[40]).id),
        PartnerRequest(stage_id=stage.id, from_entry_id=_entry(stage, order[40]).id, to_entry_id=_entry(stage, order[10]).id),
    ])
    db.session.flush()

    before = _counts(stage)
    projection = teams_divisions.project(stage)
    assert _counts(stage) == before  # nothing written
    assert projection.extra_pair_tier is None and len(projection.divisions) == 6

    teams_pairing.close(stage)
    built = teams_divisions.build_divisions(stage)
    assert _board(projection.divisions) == _board(built)
    # projected pairs that already existed carry their id; the rest are new
    formed = {p.id for p in teams_pairing.stage_pairs(stage)}
    assert all(p.pair_id is None or p.pair_id in formed for d in projection.divisions for p in d.pairs)


def _entry(stage, player_id):
    return Entry.query.filter_by(competition_id=stage.competition_id, player_id=player_id).one()


def test_extra_pair_lands_where_declaring_it_puts_it(pg):
    stage = _stage()
    order = _by_position(stage)
    a, b = order[0], order[-1]  # best with worst: not what the auto-pairing does
    projection = teams_divisions.project(stage, extra_pair=(a, b), now=NOW)
    assert projection.extra_pair == (a, b)
    assert all(d.points == sum(p.points for p in d.pairs) for d in projection.divisions)
    extra = next(p for d in projection.divisions for p in d.pairs if p.formed_by == "extra")
    assert set(extra.players) == {a, b}
    assert (projection.extra_pair_tier, projection.extra_pair_seed) != (None, None)

    teams_pairing.declare(stage, a, b, now=NOW)
    teams_pairing.declare(stage, b, a, now=NOW)
    teams_pairing.close(stage)
    built = teams_divisions.build_divisions(stage)
    assert _board(projection.divisions) == _board(built)
    tier, seed = next(
        (g.tier, i) for g, division in built for i, sp in enumerate(division, 1) if set(sp.players) == {a, b}
    )
    assert (projection.extra_pair_tier, projection.extra_pair_seed) == (tier, seed)


def test_extra_pair_replaces_a_pending_choice(pg):
    stage = _stage()
    order = _by_position(stage)
    a, b, c = order[2], order[3], order[30]
    teams_pairing.declare(stage, c, a, now=NOW)  # c wants a; a now simulates b
    projection = teams_divisions.project(stage, extra_pair=(a, b), now=NOW)
    players = {p.players: p.formed_by for d in projection.divisions for p in d.pairs}
    assert players[(a, b)] == "extra"
    assert all(c not in pair or how == "ranking" for pair, how in players.items())


def test_extra_pair_is_validated_like_a_choice(pg):
    stage = _stage()
    order = _by_position(stage)
    teams_pairing.declare(stage, order[0], order[1], now=NOW)
    teams_pairing.declare(stage, order[1], order[0], now=NOW)
    for bad in ((order[0], order[2]), (order[3], order[3]), (order[3], 10**9)):
        with pytest.raises(PairingError):
            teams_divisions.project(stage, extra_pair=bad, now=NOW)

    # 3 mini-tournaments together already: a 4th is refused
    a, b = order[4], order[6]
    ea, eb = sorted((_entry(stage, a).id, _entry(stage, b).id))
    others = Stage.query.filter(Stage.competition_id == stage.competition_id, Stage.id != stage.id).all()[:3]
    if len(others) < 3:
        pytest.skip("needs 3 other stages")
    db.session.add_all([Pair(stage_id=s.id, entry_a_id=ea, entry_b_id=eb, formed_by="manual") for s in others])
    db.session.flush()
    with pytest.raises(PairingError):
        teams_divisions.project(stage, extra_pair=(a, b), now=NOW)
    assert teams_divisions.project(stage, extra_pair=(a, order[7]), now=NOW).extra_pair_tier is not None


def test_closed_stage_projects_its_pairs_and_refuses_an_extra(pg):
    stage = _stage()
    teams_pairing.close(stage)
    projection = teams_divisions.project(stage)
    assert projection.pairing_closed and all(p.pair_id for d in projection.divisions for p in d.pairs)
    assert _board(projection.divisions) == _board(teams_divisions.build_divisions(stage))
    order = _by_position(stage)
    with pytest.raises(PairingError):
        teams_divisions.project(stage, extra_pair=(order[0], order[1]), now=NOW)


def test_after_the_deadline_the_board_works_but_an_extra_pair_is_refused(pg):
    stage = _stage()
    late = datetime(2026, 10, 19, 9, 0)
    order = _by_position(stage)
    with pytest.raises(PairingError):
        teams_divisions.project(stage, extra_pair=(order[0], order[1]), now=late)
    assert len(teams_divisions.project(stage, now=late).divisions) == 6


# --- project_partners ---------------------------------------------------------------


def test_partners_match_single_projections_and_seed_once(pg, monkeypatch):
    stage = _stage()
    order = _by_position(stage)
    a = order[20]
    x, y, d1, d2 = order[0], order[1], order[30], order[31]
    teams_pairing.declare(stage, x, y, now=NOW)
    teams_pairing.declare(stage, y, x, now=NOW)  # formed pair
    teams_pairing.declare(stage, d1, a, now=NOW)  # d1 chose a
    teams_pairing.declare(stage, a, d2, now=NOW)  # a chose d2

    calls = []
    real = ranking.seeding
    monkeypatch.setattr(ranking, "seeding", lambda league_id: calls.append(league_id) or real(league_id))
    before = _counts(stage)
    sim = teams_divisions.project_partners(stage, a, selected=order[25], now=NOW)
    assert len(calls) == 1 and _counts(stage) == before

    status = {o.player_id: o.status for o in sim.options}
    assert status[x] == f"paired_with:{y}" and status[d1] == "declared_you" and status[d2] == "you_declared"
    assert len(sim.options) == len(order) - 1 and a not in status
    by_b = {o.player_id: o for o in sim.options}
    assert not by_b[x].allowed and by_b[x].tier is None

    base = teams_divisions.project(stage)
    base_place = teams_divisions._placement(base, a)
    assert sim.baseline == base_place
    for b in (order[5], order[25], order[47]):
        single = teams_divisions.project(stage, extra_pair=(a, b), now=NOW)
        o = by_b[b]
        assert (o.tier, o.seed) == (single.extra_pair_tier, single.extra_pair_seed)
        assert o.pair_points == by_b[b].points + sim.player_points
        assert o.delta_vs_baseline == o.pair_points - base_place.points

    chosen = teams_divisions.project(stage, extra_pair=(a, order[25]), now=NOW)
    k = chosen.extra_pair_tier
    assert sim.selected_placement.tier == k and sim.thresholds.tier == k
    tiers = {d.tier: d for d in chosen.divisions}
    assert sim.thresholds.weakest_above == (min(p.points for p in tiers[k - 1].pairs) if k > 1 else None)
    assert sim.thresholds.best_below == (max(p.points for p in tiers[k + 1].pairs) if k < 6 else None)


def test_partners_played_together_and_fourth_time(pg):
    stage = _stage()
    order = _by_position(stage)
    a, c = order[10], order[11]
    ea, ec = sorted((_entry(stage, a).id, _entry(stage, c).id))
    others = Stage.query.filter(Stage.competition_id == stage.competition_id, Stage.id != stage.id).order_by(Stage.number).all()[:3]
    if len(others) < 3:
        pytest.skip("needs 3 other stages")
    db.session.add_all([Pair(stage_id=s.id, entry_a_id=ea, entry_b_id=ec, formed_by="manual") for s in others])
    db.session.flush()
    o = next(o for o in teams_divisions.project_partners(stage, a, now=NOW).options if o.player_id == c)
    assert o.played_together == tuple(s.number for s in others)
    assert not o.allowed and "4.º" in o.reason


def test_partners_after_the_deadline_show_the_baseline_only(pg):
    stage = _stage()
    order = _by_position(stage)
    sim = teams_divisions.project_partners(stage, order[3], now=datetime(2026, 10, 19, 9, 0))
    assert not sim.choice_open and sim.baseline.tier is not None
    assert all(not o.allowed and o.reason for o in sim.options)
    assert sim.thresholds.tier == sim.baseline.tier
