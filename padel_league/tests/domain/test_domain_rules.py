"""Pure rule tests (no database): Teams reference case, Shuffle curve, Clássica order, ranking rules."""

from datetime import date

import pytest

from padel_league.domain.awards import TEAMS_RATINGS, group_awards, place_points, shuffle_curve
from padel_league.domain.errors import InvalidInput
from padel_league.domain.ranking import AwardFact, CompetitionFact, Rule, compute
from padel_league.domain.standings import (
    MatchFacts,
    Member,
    SetResult,
    classica_standings,
    teams_standings,
)

W = SetResult(6, 2)  # home wins the set
L = SetResult(2, 6)  # away wins the set
T = SetResult(3, 3, "timeout_draw")
N = SetResult(None, None, "not_started")

# --- Teams reference case (docs/v2/teams/reference.md) --------------------------------

P = {n: n for n in range(1, 9)}  # entry id = player id = n for P1..P8
A, B, C, D = (1, 2), (3, 4), (5, 6), (7, 8)


def _members():
    return [Member(entry_id=n, player_id=n, order=n) for n in range(1, 9)]


def _reference_matches():
    without = lambda pair, absent: tuple(e for e in pair if e != absent)  # noqa: E731
    return [
        # J1: A–B 3-0 · C–D 1-1 with 1 draw · P4 absent
        MatchFacts(1, A, without(B, 4), (W, W, W)),
        MatchFacts(1, C, D, (W, L, T)),
        # J2: A–C 2-1 · B–D 1-1 with 1 draw · P2 absent
        MatchFacts(2, without(A, 2), C, (W, W, L)),
        MatchFacts(2, B, D, (L, W, N)),
        # J3: A–D 1-0 with 2 draws (time-out) · B–C 3-0
        MatchFacts(3, A, D, (W, T, N)),
        MatchFacts(3, B, C, (W, W, W)),
    ]


EXPECTED = {  # player: (place, pts, presences, sets won, sets drawn, place points, bonus, total)
    1: (1, 20, 3, 6, 2, 500, 34, 534),
    2: (2, 14, 2, 4, 2, 375, 24, 399),
    3: (3, 13, 3, 4, 1, 281, 22, 303),
    4: (4, 13, 2, 4, 1, 210, 22, 232),
    7: (5, 10, 3, 2, 4, 158, 18, 176),
    8: (5, 10, 3, 2, 4, 158, 18, 176),
    5: (7, 7, 3, 2, 1, 88, 12, 100),
    6: (7, 7, 3, 2, 1, 88, 12, 100),
}


def test_teams_reference_case():
    rows = teams_standings(_members(), _reference_matches())
    awards = {a.player_id: a for a in group_awards(rows, TEAMS_RATINGS[1])}
    got = {
        r.player_id: (
            r.place,
            r.points,
            r.appearances,
            r.sets_won,
            r.sets_drawn,
            awards[r.player_id].place_points,
            awards[r.player_id].bonus_points,
            awards[r.player_id].total,
        )
        for r in rows
    }
    assert got == EXPECTED
    assert [r.player_id for r in rows] == [1, 2, 3, 4, 7, 8, 5, 6]


def test_teams_match_needs_exactly_three_sets():
    with pytest.raises(InvalidInput) as err:
        teams_standings(_members(), [MatchFacts(1, A, B, (W, W))])
    assert err.value.code == "teams_needs_three_sets"


def test_teams_completed_set_needs_a_winner():
    with pytest.raises(InvalidInput):
        teams_standings(_members(), [MatchFacts(1, A, B, (W, W, SetResult(4, 4)))])


def test_teams_walkover_is_three_sets_to_nil_and_absent_pair_scores_nothing():
    rows = {r.player_id: r for r in teams_standings(_members(), [MatchFacts(1, A, (), walkover_winner="home")])}
    assert (rows[1].points, rows[1].sets_won, rows[1].appearances) == (9, 3, 1)
    assert (rows[3].points, rows[3].appearances) == (0, 0)


def test_teams_walkover_player_who_turned_up_keeps_the_presence():
    # P3 came, P4 did not and no substitute was found: B loses by walkover
    rows = {r.player_id: r for r in teams_standings(_members(), [MatchFacts(1, A, (3,), walkover_winner="home")])}
    assert (rows[3].points, rows[3].appearances, rows[3].sets_lost) == (0, 1, 0)
    assert (rows[4].points, rows[4].appearances) == (0, 0)


def test_teams_no_set_finished_gives_three_draws():
    rows = {r.player_id: r for r in teams_standings(_members(), [MatchFacts(1, A, B, (T, N, N))])}
    assert rows[1].points == rows[3].points == 3


def test_teams_no_results_everyone_shares_first_place():
    assert {r.place for r in teams_standings(_members(), [])} == {1}


def test_teams_ratings_are_not_divided_again():
    assert TEAMS_RATINGS == {1: 500, 2: 250, 3: 125, 4: 63, 5: 31, 6: 16}
    # 63 / 100 is not an integer: bonus stays unrounded
    assert group_awards(teams_standings(_members(), _reference_matches())[:1], 63)[0].bonus_points == pytest.approx(
        6 * 0.63 + 2 * 63 / 250
    )


# --- Shuffle curve ---------------------------------------------------------------------

SHUFFLE_TABLE = [
    2000, 1700, 1444, 1228, 1044, 887, 754, 641, 577, 519, 467, 420, 378, 340, 306, 275,
    248, 223, 201, 181, 162, 146, 132, 118, 106, 96, 86, 77, 70, 63, 56, 51,
    46, 41, 37, 33, 30, 27, 24, 22, 19, 17, 16, 14, 12, 11, 10, 9,
]  # fmt: skip


def test_shuffle_curve_full_table():
    curve = shuffle_curve()
    assert curve == [float(v) for v in SHUFFLE_TABLE]
    assert (curve[7], curve[47], sum(curve)) == (641, 9, 15364)
    assert curve[2] == 1444  # 2000·0.85² = 1444.999… truncated, not 1445


# --- Clássica ------------------------------------------------------------------------


def test_classica_order_points_then_presences_then_games_difference():
    members = [Member(n, n, n) for n in range(1, 5)]
    matches = [
        MatchFacts(1, (1, 2), (3, 4), (SetResult(6, 4),)),  # 1,2 win by 2
        MatchFacts(1, (1, 3), (2, 4), (SetResult(6, 1),)),  # 1,3 win by 5
        MatchFacts(1, (1, 4), (2,), (SetResult(4, 6),)),  # 2 wins by 2, 3 absent
    ]
    rows = classica_standings(members, matches)
    # 1: 6 pts 3 pres; 2: 6 pts 3 pres, diff 2-5+2=-1 vs 1: 2+5-2=+5; 3: 3 pts 2 pres; 4: 0 pts
    assert [(r.player_id, r.place, r.points, r.appearances) for r in rows] == [
        (1, 1, 6, 3),
        (2, 2, 6, 3),
        (3, 3, 3, 2),
        (4, 4, 0, 3),
    ]
    assert rows[0].attendance_pct == 100.0  # B3: was stored as 787.5
    assert rows[2].attendance_pct == pytest.approx(200 / 3)


def test_classica_award_formula():
    assert place_points(2000, 1) == 2000
    assert place_points(63, 2) == 47  # int(47.25)
    assert place_points(500, 5) == 158


# --- Ranking rules ----------------------------------------------------------------------


def _comp(id, status="ended", ends=None, fmt="classica", slot=None):
    return CompetitionFact(id=id, format=fmt, status=status, ends_on=ends, event_slot_id=slot)


COMPS = [
    _comp(21, ends=date(2025, 10, 14), slot=1),
    _comp(22, ends=date(2025, 12, 2), slot=2),
    _comp(23, ends=date(2026, 2, 17), slot=3),
    _comp(26, ends=date(2026, 4, 1), fmt="shuffle", slot=4),
    _comp(24, ends=date(2026, 6, 23), slot=1),
    _comp(27, status="running", fmt="teams", slot=5),
    CompetitionFact(14, "classica", "planned", None, date(2024, 5, 29)),  # stale planned row
]
AWARDS = [AwardFact(player_id=1, competition_id=c.id, place_points=100.0 * c.id, bonus_points=0.5) for c in COMPS]


def test_last_n_by_id_ignores_status_and_dates():
    r = compute(Rule("last_n_by_id", 4), COMPS[:-1], AWARDS)
    assert r.counted_competition_ids == [23, 24, 26, 27]


def test_last_n_completed_plus_current_orders_by_end_date():
    r = compute(Rule("last_n_completed_plus_current", 3), COMPS, AWARDS)
    assert r.counted_competition_ids == [23, 24, 26, 27]
    assert r.points_of(1) == pytest.approx(100 * (23 + 24 + 26 + 27) + 4 * 0.5)  # unrounded


def test_formats_option_decides_whether_shuffle_counts():
    r = compute(Rule("last_n_completed_plus_current", 3, {"formats": ["classica", "teams"]}), COMPS, AWARDS)
    assert r.counted_competition_ids == [22, 23, 24, 27]
    explain = {l.competition_id: l for l in r.explain[1]}
    assert not explain[26].counted and explain[22].counted


def test_per_slot_latest_instance_replaces_its_counterpart():
    r = compute(Rule("per_slot"), COMPS[:-1], AWARDS)
    assert r.counted_competition_ids == [22, 23, 24, 26, 27]  # 24 replaces 21 (slot 1)


def test_positions_are_distinct_points_then_previous_position():
    awards = [AwardFact(p, 24, 100.0, 0) for p in (5, 6)] + [AwardFact(7, 24, 300.0, 0)]
    r = compute(Rule("last_n_by_id", 4), COMPS[:-1], awards, previous_positions={6: 1, 5: 2})
    assert [(l.player_id, l.position) for l in r.lines] == [(7, 1), (6, 2), (5, 3)]


def test_unknown_rule_is_refused():
    with pytest.raises(InvalidInput):
        compute(Rule("best_of"), COMPS, AWARDS)
