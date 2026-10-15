"""Shuffle on v2: overall order and round generation (Postgres, rolled back)."""

import pytest

from padel_league.domain.errors import Conflict
from padel_league.models.v2 import CompetitionGroup, CompetitionMatch, GroupMember, Stage, StandingSnapshot
from padel_league.services import shuffle
from padel_league.services.standings import competition_standings
from padel_league.sql_db import db

SHUFFLE = 26


def _drop_stored_final_places():
    from padel_league.models.v2 import Entry

    ids = [e.id for e in Entry.query.filter_by(competition_id=SHUFFLE)]
    StandingSnapshot.query.filter(
        StandingSnapshot.entry_id.in_(ids), StandingSnapshot.group_member_id.is_(None)
    ).delete(synchronize_session=False)


def test_live_overall_order_matches_the_stored_final_positions(pg):
    stored = {r.player_id: r.place for r in competition_standings(SHUFFLE).rows}
    _drop_stored_final_places()
    live = {r.player_id: r.place for r in competition_standings(SHUFFLE).rows}
    assert live == stored


def test_generate_round_then_delete_it(pg):
    before = {s.number for s in Stage.query.filter_by(competition_id=SHUFFLE)}
    divisions = shuffle.next_divisions(SHUFFLE)
    assert [len(divisions[t]) for t in sorted(divisions)] == [8] * 6

    stage = shuffle.generate_round(SHUFFLE)
    assert stage.number == max(before) + 1
    groups = CompetitionGroup.query.filter_by(stage_id=stage.id).order_by(CompetitionGroup.tier).all()
    assert [g.multiplier for g in groups] == [10, 8, 6, 5, 4, 3]
    top = groups[0]
    seats = [gm.entry_id for gm in GroupMember.query.filter_by(group_id=top.id).order_by(GroupMember.seed)]
    assert seats == divisions[1]
    matches = CompetitionMatch.query.filter_by(group_id=top.id).order_by(CompetitionMatch.id).all()
    assert len(matches) == 6
    first = {(p.side, p.entry_id) for p in matches[0].participants}
    assert first == {("home", seats[0]), ("home", seats[7]), ("away", seats[1]), ("away", seats[6])}

    with pytest.raises(Conflict) as err:
        shuffle.generate_round(SHUFFLE)
    assert err.value.code == "round_unfinished"

    shuffle.delete_last_round(SHUFFLE)
    db.session.flush()
    assert {s.number for s in Stage.query.filter_by(competition_id=SHUFFLE)} == before
