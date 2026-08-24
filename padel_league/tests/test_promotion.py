"""The promotion/relegation cascade.

The reference case is the real one: edition 24 (Primavera 2026) rolling into
edition 25, with six withdrawals. Those expectations were checked against the
layout the league actually approved, so they pin the rule down.
"""

import pytest

from padel_league.services.promotion import (
    PromotionError,
    next_edition_layout,
    vacancies,
)


def standing(division, place, player_id, appearances=0, career=0):
    return {
        "division": division,
        "place": place,
        "player_id": player_id,
        "appearances": appearances,
        "career_appearances": career,
    }


def simple(divisions=3, size=8):
    """Player ids encode position: division*100 + place."""
    return [
        standing(d, p, d * 100 + p, appearances=size - p)
        for d in range(1, divisions + 1)
        for p in range(1, size + 1)
    ]


def test_no_withdrawals_is_plain_two_up_two_down():
    layout, decisions = next_edition_layout(simple())
    assert decisions == []
    assert sorted(layout[1]) == sorted([101, 102, 103, 104, 105, 106, 201, 202])
    assert sorted(layout[2]) == sorted([107, 108, 203, 204, 205, 206, 301, 302])
    assert sorted(layout[3]) == sorted([207, 208, 303, 304, 305, 306, 307, 308])
    assert all(len(v) == 8 for v in layout.values())


def test_top_division_keeps_its_top_two_and_bottom_keeps_its_bottom_two():
    layout, _ = next_edition_layout(simple())
    assert 101 in layout[1] and 102 in layout[1]  # nowhere to be promoted to
    assert 307 in layout[3] and 308 in layout[3]  # nowhere to be relegated to


def test_a_withdrawal_leaves_the_hole_where_the_player_was_going_not_where_they_were():
    # 301 would have been promoted into division 2, so division 2 is short.
    layout, decisions = next_edition_layout(simple(), withdrawn={301})
    assert 301 not in layout[2]
    assert [d["division"] for d in decisions] == [2]


def test_one_hole_is_a_contest_won_on_appearances():
    rows = simple()
    seventh = next(s for s in rows if s["division"] == 1 and s["place"] == 7)
    third = next(s for s in rows if s["division"] == 2 and s["place"] == 3)
    seventh["appearances"], third["appearances"] = 21, 12

    # remove a division-1 stayer so division 1 is one short
    layout, decisions = next_edition_layout(rows, withdrawn={104})
    assert 107 in layout[1]  # the 7º kept his place
    assert decisions[0]["reason"].startswith("21 appearances vs 12")


def test_one_hole_can_be_won_by_the_division_below():
    rows = simple()
    seventh = next(s for s in rows if s["division"] == 1 and s["place"] == 7)
    third = next(s for s in rows if s["division"] == 2 and s["place"] == 3)
    seventh["appearances"], third["appearances"] = 9, 21

    layout, _ = next_edition_layout(rows, withdrawn={104})
    assert 203 in layout[1]  # the 3º of division 2 went up
    assert 107 not in layout[1]


def test_a_tie_on_appearances_is_broken_on_career_appearances():
    rows = simple()
    seventh = next(s for s in rows if s["division"] == 1 and s["place"] == 7)
    third = next(s for s in rows if s["division"] == 2 and s["place"] == 3)
    seventh["appearances"] = third["appearances"] = 18
    seventh["career_appearances"], third["career_appearances"] = 192, 69

    layout, decisions = next_edition_layout(rows, withdrawn={104})
    assert 107 in layout[1]
    assert "career appearances 192 vs 69" in decisions[0]["reason"]


def test_two_holes_take_both_candidates():
    layout, decisions = next_edition_layout(simple(), withdrawn={104, 105})
    assert 107 in layout[1] and 203 in layout[1]
    assert all("both candidates" in d["reason"] for d in decisions[:2])


def test_three_holes_step_out_to_the_eighth_and_fourth():
    layout, decisions = next_edition_layout(simple(), withdrawn={104, 105, 106})
    roles = [d["role"] for d in decisions if d["division"] == 1]
    assert roles[:2] == ["7º of 1 not relegated", "3º of 2 promoted"]
    assert roles[2] in ("8º of 1 not relegated", "4º of 2 promoted")


def test_four_holes_take_both_of_the_second_pair_too():
    layout, decisions = next_edition_layout(simple(), withdrawn={103, 104, 105, 106})
    taken = {d["player_id"] for d in decisions if d["division"] == 1}
    assert {107, 203} <= taken
    assert {108, 204} <= taken


def test_a_hole_cascades_down_the_ladder():
    layout, decisions = next_edition_layout(simple(divisions=4), withdrawn={104})
    # every division above the bottom had to resolve something
    assert {d["division"] for d in decisions} == {1, 2, 3}
    assert len(layout[4]) == 7  # the hole ends up at the bottom, for a newcomer


def test_when_both_candidates_withdrew_the_next_pair_is_tried():
    # 107 (the 7º) and 203 (the 3º below) are both gone, plus a stayer to make
    # the hole in the first place.
    layout, decisions = next_edition_layout(simple(), withdrawn={104, 107, 203})
    roles = [d["role"] for d in decisions if d["division"] == 1]
    assert roles, "expected division 1 to be filled from the next pair down"
    assert roles[0] in ("8º of 1 not relegated", "4º of 2 promoted")


def test_reserved_slots_are_not_cascaded():
    # A newcomer is taking the division-1 hole, so nothing should move up.
    layout, decisions = next_edition_layout(simple(), withdrawn={104}, reserved={1: 1})
    assert decisions == []
    assert len(layout[1]) == 7  # waiting for the incoming player


def test_missing_places_are_rejected_rather_than_guessed():
    rows = [s for s in simple() if not (s["division"] == 2 and s["place"] == 5)]
    with pytest.raises(PromotionError, match="missing places"):
        next_edition_layout(rows)


def test_empty_standings_rejected():
    with pytest.raises(PromotionError, match="no standings"):
        next_edition_layout([])


def test_vacancies_reports_what_newcomers_must_fill():
    layout, _ = next_edition_layout(simple(divisions=4), withdrawn={104})
    assert vacancies(layout) == {4: 1}


# ── the real edition 24 -> 25 case ───────────────────────────────────────────

ED24 = {
    1: [
        (45, 21, 63),
        (27, 15, 270),
        (28, 15, 285),
        (18, 15, 298),
        (32, 18, 226),
        (16, 12, 246),
        (21, 12, 332),
        (56, 18, 94),
    ],
    2: [
        (13, 21, 337),
        (7, 21, 300),
        (4, 18, 200),
        (14, 21, 250),
        (11, 18, 210),
        (64, 21, 100),
        (37, 18, 241),
        (34, 18, 180),
    ],
    3: [
        (77, 15, 15),
        (50, 15, 120),
        (76, 21, 81),
        (3, 12, 150),
        (88, 18, 90),
        (51, 21, 130),
        (57, 21, 99),
        (26, 6, 250),
    ],
    4: [
        (62, 21, 160),
        (91, 15, 60),
        (38, 18, 190),
        (52, 21, 170),
        (84, 21, 140),
        (86, 21, 110),
        (100, 9, 9),
        (42, 18, 192),
    ],
    5: [
        (44, 18, 120),
        (61, 21, 130),
        (92, 21, 21),
        (80, 18, 69),
        (59, 21, 105),
        (40, 18, 115),
        (97, 21, 60),
        (79, 21, 84),
    ],
    6: [
        (103, 21, 21),
        (87, 21, 40),
        (102, 18, 18),
        (2, 21, 63),
        (78, 21, 50),
        (31, 18, 45),
        (104, 12, 12),
        (99, 15, 15),
    ],
}
REAL = [
    standing(d, i + 1, pid, app, career)
    for d, rows in ED24.items()
    for i, (pid, app, career) in enumerate(rows)
]
# Perneta, João Bello, Kikos, Gonçalo Ramalho, To maria, Diogo Leão
WITHDRAWN = {18, 77, 26, 100, 92, 3}


def test_real_edition_25_layout_matches_what_the_league_approved():
    layout, _ = next_edition_layout(
        REAL, withdrawn=WITHDRAWN, reserved={1: 1}  # Miguel SG takes the 1ª hole
    )
    assert layout[1] == [45, 27, 28, 32, 16, 13, 7]
    assert sorted(layout[2]) == sorted([21, 56, 4, 14, 11, 64, 50, 76])
    assert sorted(layout[3]) == sorted([37, 34, 88, 51, 57, 62, 91, 38])
    assert sorted(layout[4]) == sorted([52, 84, 86, 42, 44, 61, 80, 59])
    assert sorted(layout[5]) == sorted([40, 97, 79, 103, 87, 102, 2, 78])
    assert sorted(layout[6]) == sorted([31, 104, 99])


def test_real_case_leaves_exactly_the_slots_the_newcomers_filled():
    layout, _ = next_edition_layout(REAL, withdrawn=WITHDRAWN, reserved={1: 1})
    assert vacancies(layout) == {1: 1, 6: 5}
    assert sum(len(v) for v in layout.values()) == 42  # + 6 incoming = 48


def test_real_case_records_why_each_contest_went_the_way_it_did():
    _, decisions = next_edition_layout(REAL, withdrawn=WITHDRAWN, reserved={1: 1})
    by_player = {d["player_id"]: d["reason"] for d in decisions}

    # Only one hole in the real case was an actual head-to-head: the 2ª, where
    # Cou (3º of the 3ª) beat Gonçalo PA (7º of the 2ª) on appearances.
    assert "21 appearances vs 18" in by_player[76]
    contests = [r for r in by_player.values() if "appearances vs" in r]
    assert len(contests) == 1

    # Everything else fell out of even hole counts or an empty pair. In the 4ª
    # both first-pair candidates had withdrawn (Gonçalo Ramalho and To maria),
    # so it stepped to the 8º/4º pair and took both.
    assert by_player[42] == "two holes, both candidates take one"  # Ricas
    assert by_player[80] == "two holes, both candidates take one"  # Pedro AR
    assert by_player[59] == "only candidate available"  # Hugo
