"""Results → close-out → awards → ranking on Postgres (template clone, rolled back)."""

import pytest

from padel_league.domain.errors import Conflict, InvalidInput
from padel_league.models import Player
from padel_league.models.v2 import Award, AwardEvent, Competition, RankingSnapshot, StandingSnapshot
from padel_league.services import closeout, ranking, results
from padel_league.sql_db import db
from padel_league.tests import factories as f

W = {"home_games": 6, "away_games": 2}
L = {"home_games": 2, "away_games": 6}
T = {"home_games": 3, "away_games": 3, "outcome": "timeout_draw"}
N = {"outcome": "not_started"}


def _teams_reference_group():
    comp = f.competition(format="teams", name="Teams reference")
    stg = f.stage(comp, emits_award=True)
    grp = f.group(stg, tier=1, rating=None)
    e = {n: f.entry(comp, f.player()) for n in range(1, 9)}
    for n in range(1, 9):
        f.member(grp, e[n])
    rounds = {n: f.round_(stg, n) for n in (1, 2, 3)}
    pairs = {"A": (1, 2), "B": (3, 4), "C": (5, 6), "D": (7, 8)}
    absent = {1: 4, 2: 2}
    fixtures = [  # (round, home, away, sets)
        (1, "A", "B", [W, W, W]), (1, "C", "D", [W, L, T]),
        (2, "A", "C", [W, W, L]), (2, "B", "D", [L, W, N]),
        (3, "A", "D", [W, T, N]), (3, "B", "C", [W, W, W]),
    ]  # fmt: skip
    for rnd, home, away, sets in fixtures:
        side = lambda p: tuple(e[n] for n in pairs[p] if n != absent.get(rnd))  # noqa: E731
        m = f.match(grp, rounds[rnd], home=side(home), away=side(away))
        results.record_sets(m.id, sets)
    db.session.flush()
    return comp, grp, e


EXPECTED_TOTALS = {1: 534, 2: 399, 3: 303, 4: 232, 7: 176, 8: 176, 5: 100, 6: 100}
EXPECTED_PLACES = {1: 1, 2: 2, 3: 3, 4: 4, 7: 5, 8: 5, 5: 7, 6: 7}


def test_teams_reference_case_end_to_end(pg):
    comp, grp, e = _teams_reference_group()
    event = closeout.close_group(grp.id)
    by_entry = {a.entry_id: a for a in event.awards}
    assert {n: by_entry[e[n].id].total for n in e} == EXPECTED_TOTALS
    assert {n: by_entry[e[n].id].place for n in e} == EXPECTED_PLACES
    assert by_entry[e[1].id].rating == 500 and (by_entry[e[1].id].wins, by_entry[e[1].id].draws) == (6, 2)

    snaps = {s.entry_id: s for s in StandingSnapshot.query.filter(StandingSnapshot.entry_id.in_([x.id for x in e.values()]))}
    assert snaps[e[2].id].points == 14 and snaps[e[2].id].appearances == 2 and snaps[e[2].id].source == "computed"

    # B1: the ranking snapshot written by this close-out already includes the group
    snap = RankingSnapshot.query.order_by(RankingSnapshot.id.desc()).first()
    assert snap.after_award_event_id == event.id
    pts = {r.player_id: r.points for r in snap.entries}
    p1 = e[1].player_id
    assert pts[p1] == pytest.approx(534)
    assert db.session.get(Player, p1).ranking_points == 534


def test_close_refuses_incomplete_and_already_closed(pg):
    comp = f.competition(format="teams", name="Teams incomplete")
    stg = f.stage(comp)
    grp = f.group(stg, tier=2, rating=None)
    a, b = f.entry(comp, f.player()), f.entry(comp, f.player())
    f.member(grp, a), f.member(grp, b)
    m = f.match(grp, f.round_(stg, 1), home=(a,), away=(b,))
    with pytest.raises(Conflict) as err:
        closeout.close_group(grp.id)
    assert err.value.code == "group_not_complete"
    results.record_sets(m.id, walkover_winner="home")
    event = closeout.close_group(grp.id, recompute_ranking=False)
    award = {x.entry_id: x for x in event.awards}
    assert award[a.id].rating == 250 and award[a.id].total == 250 + 3 * 2.5  # 3 sets won, Teams tier 2
    with pytest.raises(Conflict) as err:
        closeout.close_group(grp.id)
    assert err.value.code == "group_already_closed"


def test_record_sets_validates_format(pg):
    comp = f.competition(format="teams", name="Teams invalid")
    stg = f.stage(comp)
    grp = f.group(stg)
    a, b = f.entry(comp, f.player()), f.entry(comp, f.player())
    m = f.match(grp, f.round_(stg, 1), home=(a,), away=(b,))
    with pytest.raises(InvalidInput) as err:
        results.record_sets(m.id, [W, W])
    assert err.value.code == "teams_needs_three_sets"
    with pytest.raises(InvalidInput):
        results.record_sets(m.id, [W, W, {"home_games": 4, "away_games": 4}])

    cl = f.competition(format="classica", name="Classica invalid")
    cstg = f.stage(cl)
    cgrp = f.group(cstg)
    cm = f.match(cgrp, f.round_(cstg, 1))
    with pytest.raises(InvalidInput):
        results.record_sets(cm.id, walkover_winner="home")
    results.record_sets(cm.id, [{"home_games": 4, "away_games": 4}])  # Clássica draws are fine
    assert cm.status == "played" and cm.sets[0].home_games == 4


def _drop_shuffle_awards():
    """Back to the pre-bootstrap state (works on a bootstrapped template too)."""
    from padel_league.models.v2 import AwardEvent, RankingSnapshot

    events = AwardEvent.query.filter_by(competition_id=26).all()
    ids = [e.id for e in events]
    if ids:
        RankingSnapshot.query.filter(RankingSnapshot.after_award_event_id.in_(ids)).delete(synchronize_session=False)
    for event in events:
        db.session.delete(event)
    db.session.flush()


def test_shuffle_awards_follow_the_curve_and_enter_the_ranking(pg):
    _drop_shuffle_awards()
    event = closeout.close_shuffle(26)
    assert len(event.awards) == 48
    assert sum(a.place_points for a in event.awards) == 15364
    assert all(a.bonus_points == 0 for a in event.awards)
    result = ranking.compute(1)
    assert 26 in result.counted_competition_ids
    pi = Player.query.filter_by(name="Pi Magalhaes").first()
    assert result.points_of(pi.id) == pytest.approx(5371)  # 2264 + 2220 + 887 (Shuffle 6th)
    assert [l.position for l in result.lines] == list(range(1, len(result.lines) + 1))
    lines = {(l.competition_id, l.counted) for l in ranking.explain(pi.id)}
    assert (26, True) in lines and (16, False) in lines  # 12ª Edição is outside the window


def test_close_shuffle_twice_is_refused(pg):
    if not db.session.get(Competition, 26):
        pytest.skip("no Shuffle 26 in template")
    _drop_shuffle_awards()
    closeout.close_shuffle(26, recompute_ranking=False)
    with pytest.raises(Conflict):
        closeout.close_shuffle(26, recompute_ranking=False)
