"""Teams divisions builder: pure seeding + the real 2026/27 roster on Postgres."""

from datetime import datetime

import pytest

from padel_league.domain.errors import Conflict
from padel_league.models.v2 import Competition, CompetitionMatch, GroupMember, Stage
from padel_league.services import closeout, ranking, results, teams_divisions, teams_pairing
from padel_league.services.teams_divisions import (
    ProjectedDivision,
    ProjectedPair,
    pair_best,
    pair_movements,
    pair_worst,
    seed_pairs,
    slice_divisions,
)
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
    with pytest.raises(teams_pairing.PairingError) as err:  # v1 endpoints catch PairingError only
        teams_pairing.close(stage)
    assert err.value.__cause__.code == "ranking_missing_awards"


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


def test_walkover_on_a_built_match_only_the_absent_player_loses_the_presence(pg):
    comp, stage = _teams_stage1()
    ranking.bootstrap()
    teams_pairing.close(stage)
    group, division = teams_divisions.build_divisions(stage)[5]
    match = CompetitionMatch.query.filter_by(group_id=group.id).order_by(CompetitionMatch.id).first()
    home = [p.entry_id for p in match.participants if p.side == "home"]
    came, absent = [(p.entry_id, p.player_id) for p in match.participants if p.side == "away"]
    results.mark_absent(group.id, match.round.number, absent[1])  # no substitute found
    results.record_sets(match.id, walkover_winner="home")
    db.session.flush()
    db.session.expire_all()
    from padel_league.services.standings import group_standings

    rows = {r.entry_id: r for r in group_standings(group.id).rows}
    assert all((rows[e].points, rows[e].appearances, rows[e].sets_won) == (9, 1, 3) for e in home)
    assert (rows[came[0]].points, rows[came[0]].appearances) == (0, 1)  # turned up: keeps the presence
    assert (rows[absent[0]].points, rows[absent[0]].appearances) == (0, 0)


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


def test_building_the_first_divisions_starts_the_competition(pg):
    """Prod, Oct 2026: Teams 2026/27 stayed 'planned' (card said "upcoming") with 24 matches
    played — nothing flipped it. Building a mini-tournament's divisions starts the Teams."""
    comp, stage = _teams_stage1()
    ranking.bootstrap()
    teams_pairing.close(stage)
    comp.status = "planned"
    teams_divisions.build_divisions(stage)
    assert stage.status == "running" and comp.status == "running"


def test_building_divisions_leaves_a_started_or_ended_competition_alone(pg):
    comp, stage = _teams_stage1()
    ranking.bootstrap()
    teams_pairing.close(stage)
    comp.status = "running"
    teams_divisions.build_divisions(stage)
    assert comp.status == "running"
    # An ended Teams never gets new divisions: the seeding guard refuses it first (no awards
    # for an "ended" competition in the window), and its status is left as it was.
    comp.status = "ended"
    stage2 = Stage.query.filter_by(competition_id=comp.id, number=2).one()
    stage2.pairing_deadline = datetime(2026, 10, 18, 23, 0)
    with pytest.raises(Conflict):
        teams_divisions.build_divisions(stage2)
    assert comp.status == "ended"


# Competition 27 after mini-tournament 1 was formed (live seeds read on 2026-10-30, 2 decimals).
LIVE_SEEDS = {
    1: [("Pancho & Pi Magalhaes", 7062.00), ("Malafaya & Nathan", 6599.00), ("Miguel SG & Bernardo C", 5426.00), ("Talinho & Dudas", 3588.00)],
    2: [("Miguel C. & Semelhe", 3398.92), ("Cuca & Henrique", 3385.00), ("Dinis & Gonçalo PA", 2818.00), ("Zé Santos & Falcão", 2663.50)],
    3: [("Afonso Martinho & Freitas", 2603.00), ("Damásio & Lopo Sottomayor", 1779.00), ("Tomás Pacheco & Luís Folhadela", 970.50), ("Cou & Dainis", 827.25)],
    4: [("Fred Baptista & Fezas", 798.50), ("Trepa & João Mendonça", 528.75), ("Tomás Duarte & Nuno Azevedo", 433.45), ("Martinho & Antonio A", 405.56)],
    5: [("Cameira & João Leite", 392.00), ("Hugo & Pedro AR Pacheco", 379.75), ("Ricas & Manel Serôdio", 372.82), ("Bucas & Kiko SS Faro", 148.67)],
    6: [("João Ribeiro & João Lello", 93.00), ("Diogo Garrett & Zé Pedro Graça", 88.09), ("Zema & Bernardo Vasconcelos", 78.36), ("La Serna & Álvaro Van Zeller", 67.81)],
}
RATINGS = {1: 500, 2: 250, 3: 125, 4: 63, 5: 31, 6: 16}


def _live_divisions():
    divisions, names, pid = [], {}, 0
    for tier, pairs in LIVE_SEEDS.items():
        d = ProjectedDivision(tier, f"{tier}.ª Divisão", RATINGS[tier])
        for seed, (name, points) in enumerate(pairs, start=1):
            pid += 1
            names[name] = pid
            d.pairs.append(ProjectedPair(pid, (), points, None, "mutual", seed))
        divisions.append(d)
    return divisions, names


def test_pair_best_and_worst_follow_the_points_range():
    assert pair_best(500) == 2 * 545 and pair_worst(500) == 88 + 66
    assert pair_best(16) == pytest.approx(2 * 17.44) and pair_worst(16) == 2 + 2


def test_pair_movements_on_the_live_mini_tournament_1():
    """Pedro's card examples (30 Oct), verified on the live data before building."""
    divisions, names = _live_divisions()
    m = pair_movements(divisions)
    talinho = m[names["Talinho & Dudas"]]
    assert (talinho.up, talinho.down) == (False, True) and talinho.gap_up is None
    assert talinho.gap_down == pytest.approx(201.92)  # "↓ risco 202"
    miguel = m[names["Miguel C. & Semelhe"]]
    assert (miguel.up, miguel.down) == (True, False)
    assert miguel.gap_up == pytest.approx(-201.92)  # "↑ folga 202"
    dinis = m[names["Dinis & Gonçalo PA"]]
    assert (dinis.up, dinis.down) == (False, False)
    assert dinis.gap_up == pytest.approx(379.0) and dinis.gap_down == pytest.approx(-19.5)  # "↑ faltam 379 · ↓ seguro 20"
    for name, _ in LIVE_SEEDS[6]:  # the floor: nobody in the last division can go down
        assert m[names[name]].down is False and m[names[name]].gap_down is None
    assert [m[names[n]].up for n, _ in LIVE_SEEDS[6]] == [False] * 4  # 93 + 2x17.44 never reaches the 5.ª
    assert sorted(n for n, pid in names.items() if m[pid].up) == sorted(
        ["Miguel C. & Semelhe", "Cuca & Henrique", "Afonso Martinho & Freitas", "Fred Baptista & Fezas",
         "Cameira & João Leite", "Hugo & Pedro AR Pacheco", "Ricas & Manel Serôdio"]
    )
    assert sorted(n for n, pid in names.items() if m[pid].down) == sorted(
        ["Talinho & Dudas", "Zé Santos & Falcão", "Cou & Dainis", "Tomás Duarte & Nuno Azevedo", "Martinho & Antonio A"]
    )


def test_up_and_down_reduce_to_the_threshold_gaps():
    """With seeds ordered by tier and ratings falling per tier, a same-tier higher seed is
    always at least as passable as the weakest pair above, and the best pair below always
    overtakes before any same-tier lower seed does: the counting condition equals the sign
    of the gap to the neighbouring division (the coordinator's simpler test)."""
    divisions, _ = _live_divisions()
    for m in pair_movements(divisions).values():
        assert m.up == (m.gap_up is not None and m.gap_up < 0)
        assert m.down == (m.gap_down is not None and m.gap_down > 0)
