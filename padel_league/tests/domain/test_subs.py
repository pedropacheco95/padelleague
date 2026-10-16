"""Substitute points and Art. 12 (Pedro, 2026-10-16): pure rules, the ranking
fallback on Postgres, and João Mendonça's totals (273 over the ranking window,
132 in the 22ª) on a template with the SUBS_ import (V2_TEMPLATE=s1_subs_tpl;
skipped elsewhere)."""

from datetime import date

import pytest

from padel_league.domain import ranking as engine
from padel_league.domain.standings import MatchFacts, SetResult
from padel_league.domain.subs import SUBS_MULTIPLIERS, SubMatch, group_multiplier, side_points, subs_points
from padel_league.models import Player
from padel_league.models.v2 import (
    Award,
    CompetitionGroup,
    CompetitionMatch,
    MatchParticipant,
    RankingEntry,
    Stage,
)
from padel_league.services import ranking
from padel_league.sql_db import db


def _one_set(home, away):
    return MatchFacts(1, (), (), (SetResult(home, away),))


def test_side_points_per_format():
    assert [side_points("classica", _one_set(6, 3), s) for s in ("home", "away")] == [3, 0]
    assert side_points("shuffle", _one_set(4, 4), "away") == 1
    teams = MatchFacts(1, (), (), (SetResult(6, 2), SetResult(3, 6), SetResult(None, None, "timeout_draw")))
    assert side_points("teams", teams, "home") == 4  # 3 + 0 + 1
    assert side_points("teams", MatchFacts(1, (), (), (), "away"), "away") == 9
    assert side_points("classica", MatchFacts(1, (), (), ()), "home") == 0


def test_multipliers_by_tier_and_shuffle_group():
    assert [group_multiplier("classica", t) for t in range(1, 7)] == [10, 8, 6, 5, 4, 3]
    assert group_multiplier("teams", 2) == 8
    assert group_multiplier("shuffle", 1, own_multiplier=4) == 4
    assert group_multiplier("classica", 7) is None


def test_subs_points_mendonca_sheet_shape():
    # 2ª J2: one win (3 × 8); 3ª J3/J4/J6: two wins each (6 × 6)
    matches = [SubMatch(1, 2, "home", _one_set(6, 2))] + [SubMatch(1, 3, "home", _one_set(6, 1))] * 6
    matches.append(SubMatch(2, 3, "away", _one_set(6, 1)))  # lost: 0 points, still listed
    lines = subs_points(matches, {2: 8, 3: 6})
    assert [(l.player_id, l.points, l.position) for l in lines] == [(1, 132, 1), (2, 0, 2)]
    assert lines[0].by_group == {2: (3, 8, 1), 3: (18, 6, 6)}


def test_engine_fallback_only_without_a_counted_award():
    rule = engine.Rule("last_n_completed_plus_current", last_n=1)
    comps = [engine.CompetitionFact(1, "classica", "ended", ends_on=date(2026, 10, 13))]
    awards = [engine.AwardFact(player_id=10, competition_id=1, place_points=200, bonus_points=0)]
    subs = {10: (60.0, []), 20: (132.0, []), 30: (0.0, [])}
    result = engine.compute(rule, comps, awards, subs=subs)
    assert [(l.player_id, l.points, l.source) for l in result.lines] == [(10, 200, "awards"), (20, 132, "subs")]


# --- Postgres -------------------------------------------------------------------


def _free_seats(competition_id, n):
    """n (match, side, slot, tier) with an empty slot in played matches of the competition."""
    seats = []
    q = (
        db.session.query(CompetitionMatch, CompetitionGroup.tier)
        .join(CompetitionGroup, CompetitionGroup.id == CompetitionMatch.group_id)
        .join(Stage, Stage.id == CompetitionGroup.stage_id)
        .filter(Stage.competition_id == competition_id, CompetitionMatch.status == "played")
        .order_by(CompetitionMatch.id)
    )
    for match, tier in q:
        for side in ("home", "away"):
            taken = {p.slot for p in match.participants if p.side == side}
            for slot in sorted({1, 2} - taken):
                if not any(s[0].id == match.id for s in seats):
                    seats.append((match, side, slot, tier))
        if len(seats) == n:
            return seats
    pytest.skip("not enough empty seats in the last completed competition")


def _new_player(name, status):
    player = Player(name=name, full_name=name, status=status)
    db.session.add(player)
    db.session.flush()
    return player


def _sit(seat, player_id):
    match, side, slot, tier = seat
    db.session.add(MatchParticipant(match_id=match.id, side=side, slot=slot, role="substitute", player_id=player_id))
    s = sorted(match.sets, key=lambda s: s.set_no)[0]
    mine, theirs = (s.home_games, s.away_games) if side == "home" else (s.away_games, s.home_games)
    return (3 if mine > theirs else 1 if mine == theirs else 0) * SUBS_MULTIPLIERS[tier]


def _sit_value(seat):
    match, side, _, _ = seat
    s = sorted(match.sets, key=lambda s: s.set_no)[0]
    mine, theirs = (s.home_games, s.away_games) if side == "home" else (s.away_games, s.home_games)
    return mine > theirs


def test_art12_members_only_and_regulars_keep_their_points(pg):
    ranking.bootstrap()
    last = engine.last_completed(ranking.league_facts(1)[0]).id
    assert last in ranking.subs_ranking().competition_ids
    before = {l.player_id: l for l in ranking.compute(1).lines}
    regular = next(l.player_id for l in before.values() if l.source == "awards")
    seats = [
        s
        for s in _free_seats(last, 12)
        if regular not in {p.player_id for p in s[0].participants}
    ]
    newcomer, external = _new_player("Sub Novo", "member"), _new_player("Sub Externo", "external")
    # a seat with a win, so each sub really scores
    winning = [s for s in seats if _sit_value(s) > 0][:3]
    assert len(winning) == 3
    expected = {pid: _sit(seat, pid) for pid, seat in zip((newcomer.id, external.id, regular), winning)}
    db.session.flush()

    subs = {l.player_id: l.points for l in ranking.subs_ranking().lines}
    assert all(subs[pid] == pts for pid, pts in expected.items())  # the subs ranking lists everyone

    lines = {l.player_id: l for l in ranking.compute(1).lines}
    assert (lines[newcomer.id].points, lines[newcomer.id].source) == (expected[newcomer.id], "subs")
    assert external.id not in lines
    assert lines[regular].points == before[regular].points and lines[regular].source == "awards"
    assert any(e.reason.startswith("pontos de substituto") for e in ranking.explain(newcomer.id))

    snap = ranking.recompute(1, note="test art. 12")
    stored = {e.player_id: e.source for e in RankingEntry.query.filter_by(snapshot_id=snap.id)}
    assert stored[newcomer.id] == "subs" and stored[regular] == "awards" and external.id not in stored
    db.session.expire_all()
    assert db.session.get(Player, external.id).ranking_points == 0
    assert db.session.get(Player, newcomer.id).ranking_points == round(expected[newcomer.id])


def test_subs_window_defaults_to_the_ranking_window(pg):
    ranking.bootstrap()
    rule = ranking.rule_for(1)
    assert set(ranking.subs_ranking(1).competition_ids) == set(ranking.compute(1).counted_competition_ids)
    rule.options = {**(rule.options or {}), "subs_window": "last_completed"}
    last = engine.last_completed(ranking.league_facts(1)[0]).id
    assert ranking.subs_ranking(1, rule).competition_ids == [last]
    rule.options = {**rule.options, "subs_window": "everything"}
    with pytest.raises(Exception) as err:
        ranking.subs_ranking(1, rule)
    assert getattr(err.value, "code", None) == "unknown_subs_window"


def _mendonca():
    player = Player.query.filter_by(name="João Mendonça").first()
    if player is None or not MatchParticipant.query.filter_by(role="substitute", player_id=player.id).first():
        pytest.skip("template without the SUBS_ import (V2_TEMPLATE=s1_subs_tpl)")
    return player


def test_mendonca_273_over_the_ranking_window_and_seeds_once_a_member(pg):
    # sheet: Shuffle 20ª 18 + 15, 21ª 3 × 36, 22ª 132
    mendonca = _mendonca()
    ranking.bootstrap()
    sr = ranking.subs_ranking()
    assert {24, 25, 26} <= set(sr.competition_ids)
    assert {l.player_id: l.points for l in sr.lines}[mendonca.id] == 273
    assert mendonca.id not in {l.player_id for l in ranking.compute(1).lines}  # external: subs ranking only
    mendonca.status = "member"  # swap-roster: he replaces Miguel Lemos on the Teams roster
    db.session.flush()
    assert not Award.query.filter_by(player_id=mendonca.id).first()
    line = next(l for l in ranking.compute(1).lines if l.player_id == mendonca.id)
    assert (line.points, line.source) == (273, "subs")
    points, positions = ranking.seeding(1)
    assert points[mendonca.id] == 273 and positions[mendonca.id] == line.position
    # no new award event, but the stored ranking is stale: bootstrap writes it
    assert "written" in ranking.bootstrap()[-1]
    entry = RankingEntry.query.filter_by(snapshot_id=ranking.latest_snapshot(1).id, player_id=mendonca.id).one()
    assert (entry.points, entry.source) == (273, "subs")
    assert "already current" in ranking.bootstrap()[-1]


def test_mendonca_last_completed_window_is_132(pg):
    mendonca = _mendonca()
    ranking.bootstrap()
    rule = ranking.rule_for(1)
    rule.options = {**(rule.options or {}), "subs_window": "last_completed"}
    sr = ranking.subs_ranking(1, rule)
    assert sr.competition_ids == [25]
    assert {l.player_id: l.points for l in sr.lines}[mendonca.id] == 132
