"""Absences: full / partial and undo, on Postgres (rolled back)."""

import pytest

from padel_league.domain.errors import InvalidInput
from padel_league.models.v2 import Absence
from padel_league.services import results
from padel_league.sql_db import db
from padel_league.tests import factories as f


def _round_of_three():
    comp = f.competition(format="classica", name="Absence test")
    stg = f.stage(comp)
    grp = f.group(stg)
    e = [f.entry(comp, f.player()) for _ in range(4)]
    for x in e:
        f.member(grp, x)
    rnd = f.round_(stg, 1)
    ms = [
        f.match(grp, rnd, home=(e[0], e[1]), away=(e[2], e[3])),
        f.match(grp, rnd, home=(e[0], e[2]), away=(e[1], e[3])),
        f.match(grp, rnd, home=(e[0], e[3]), away=(e[1], e[2])),
    ]
    return grp, e, ms


def test_full_absence_with_substitute_then_undo_restores_slots(pg):
    grp, e, ms = _round_of_three()
    sub = f.player()
    slots = {m.id: next((p.side, p.slot) for p in m.participants if p.entry_id == e[0].id) for m in ms}
    removed, _ = results.mark_absent(grp.id, 1, e[0].player_id, substitute_player_id=sub.id)
    db.session.flush()
    assert removed == 3
    absence = Absence.query.filter_by(entry_id=e[0].id).one()
    assert absence.kind == "full"
    assert all(any(p.player_id == sub.id and p.role == "substitute" for p in m.participants) for m in ms)

    assert results.undo_absence(absence.id) == 3
    db.session.flush()
    db.session.expire_all()
    for m in ms:
        mine = [p for p in m.participants if p.entry_id == e[0].id]
        assert len(mine) == 1 and (mine[0].side, mine[0].slot) == slots[m.id] and mine[0].role == "member"
        assert not any(p.player_id == sub.id for p in m.participants)
    assert Absence.query.filter_by(entry_id=e[0].id).count() == 0


def test_partial_absence_only_touches_named_matches(pg):
    grp, e, ms = _round_of_three()
    removed, _ = results.mark_absent(grp.id, 1, e[1].player_id, match_ids=[ms[0].id])
    db.session.flush()
    assert removed == 1
    assert Absence.query.filter_by(entry_id=e[1].id).one().kind == "partial"
    assert not any(p.entry_id == e[1].id for p in ms[0].participants)
    assert any(p.entry_id == e[1].id for p in ms[1].participants)
    with pytest.raises(InvalidInput):
        results.mark_absent(grp.id, 1, e[1].player_id, match_ids=[999999999])


def test_undo_leaves_played_matches_alone(pg):
    grp, e, ms = _round_of_three()
    results.mark_absent(grp.id, 1, e[2].player_id)
    results.record_sets(ms[0].id, [{"home_games": 6, "away_games": 2}])
    db.session.flush()
    absence = Absence.query.filter_by(entry_id=e[2].id).one()
    assert results.undo_absence(absence.id) == 2
