"""Teams divisions builder: pure seeding + the real 2026/27 roster on Postgres."""

from datetime import datetime

import pytest

from padel_league.domain.errors import Conflict
from padel_league.models.v2 import Competition, CompetitionMatch, GroupMember, Stage
from padel_league.services import closeout, ranking, results, teams_divisions, teams_pairing
from padel_league.services.teams_divisions import seed_pairs, slice_divisions
from padel_league.sql_db import db


def test_seed_by_sum_then_best_individual():
    points = {1: 100, 2: 0, 3: 50, 4: 50, 5: 10, 6: 10}
    positions = {1: 1, 2: 9, 3: 2, 4: 3, 5: 4, 6: 5}
    seeded = seed_pairs([(10, (3, 4)), (11, (1, 2)), (12, (5, 6))], points, positions)
    # 100 = 100: pair 11 holds player 1 (position 1) and goes first
    assert [s.pair_id for s in seeded] == [11, 10, 12]


def test_slices_need_multiples_of_four():
    with pytest.raises(Conflict):
        slice_divisions([object()] * 6)
    assert [len(d) for d in slice_divisions(list(range(24)))] == [4] * 6


def _teams_stage1():
    comp = Competition.query.filter_by(format="teams").order_by(Competition.id.desc()).first()
    if comp is None:
        pytest.skip("no Teams competition in template")
    stage = Stage.query.filter_by(competition_id=comp.id, number=1).one()
    stage.pairing_deadline = datetime(2026, 10, 18, 23, 0)
    return comp, stage


def _without_shuffle_awards():
    """Back to the pre-bootstrap state (works on a bootstrapped template too)."""
    from padel_league.models.v2 import AwardEvent, RankingSnapshot

    events = AwardEvent.query.filter_by(competition_id=26).all()
    ids = [e.id for e in events]
    if ids:
        RankingSnapshot.query.filter(RankingSnapshot.after_award_event_id.in_(ids)).delete(synchronize_session=False)
    for event in events:
        db.session.delete(event)
    db.session.flush()


def test_seeding_refuses_while_the_shuffle_has_no_awards(pg):
    comp, stage = _teams_stage1()
    _without_shuffle_awards()
    with pytest.raises(Conflict) as err:
        teams_pairing.close(stage)
    assert err.value.code == "ranking_missing_awards"


def test_real_roster_pairs_divisions_and_first_group_close(pg):
    comp, stage = _teams_stage1()
    ranking.bootstrap()  # the cut-over step (a no-op once the template is bootstrapped)
    teams_pairing.close(stage)
    assert len(teams_pairing.stage_pairs(stage)) == 24

    built = teams_divisions.build_divisions(stage)
    assert [g.tier for g, _ in built] == [1, 2, 3, 4, 5, 6]
    assert [g.rating for g, _ in built] == [500, 250, 125, 63, 31, 16]
    sums = [sp.points for _, division in built for sp in division]
    assert sums == sorted(sums, reverse=True)
    for group, _ in built:
        assert GroupMember.query.filter_by(group_id=group.id).count() == 8
        matches = CompetitionMatch.query.filter_by(group_id=group.id).all()
        assert len(matches) == 6 and all(len(m.participants) == 4 for m in matches)

    with pytest.raises(Conflict):
        teams_divisions.build_divisions(stage)

    # play and close division 1: every match home 2 sets, 1 time-out draw
    top = built[0][0]
    for m in CompetitionMatch.query.filter_by(group_id=top.id):
        results.record_sets(m.id, [{"home_games": 6, "away_games": 3}] * 2 + [{"outcome": "timeout_draw"}])
    db.session.flush()
    event = closeout.close_group(top.id)
    assert len(event.awards) == 8 and all(a.rating == 500 for a in event.awards)
    assert max(a.place_points for a in event.awards) == 500
    # the closed mini-tournament group now counts in the live ranking (Teams = current)
    assert comp.id in ranking.compute(comp.season.league_id).counted_competition_ids


def test_walkover_on_a_built_match_gives_the_no_show_pair_nothing(pg):
    comp, stage = _teams_stage1()
    ranking.bootstrap()
    teams_pairing.close(stage)
    group, division = teams_divisions.build_divisions(stage)[5]
    match = CompetitionMatch.query.filter_by(group_id=group.id).order_by(CompetitionMatch.id).first()
    results.record_sets(match.id, walkover_winner="home")
    db.session.flush()
    from padel_league.services.standings import group_standings

    rows = {r.entry_id: r for r in group_standings(group.id).rows}
    home = [p.entry_id for p in match.participants if p.side == "home"]
    away = [p.entry_id for p in match.participants if p.side == "away"]
    assert all((rows[e].points, rows[e].appearances, rows[e].sets_won) == (9, 1, 3) for e in home)
    assert all((rows[e].points, rows[e].appearances) == (0, 0) for e in away)


def test_mirror_keeps_previously_ranked_players_nonzero(pg):
    from padel_league.models import Player

    _without_shuffle_awards()
    before = {p.id for p in Player.query.filter(Player.ranking_position > 0)}
    ranking.bootstrap()
    after = {p.id: p.ranking_position for p in Player.query.all()}
    assert all(after[pid] > 0 for pid in before)
    ranked = sorted(v for v in after.values() if v > 0)
    assert ranked == list(range(1, len(ranked) + 1))


def test_bootstrap_is_idempotent(pg):
    _without_shuffle_awards()
    first = ranking.bootstrap()
    assert first[0] == "awarded shuffle 26" and "written" in first[-1]
    assert ranking.bootstrap() == [f"ranking snapshot {ranking.latest_snapshot(1).id} already current"]
