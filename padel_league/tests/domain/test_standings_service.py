"""Standings service on Postgres (pg fixture: template clone, rolled back per test)."""

from padel_league.models.v2 import MatchSet, StandingSnapshot
from padel_league.services.standings import group_standings
from padel_league.sql_db import db
from padel_league.tests import factories as f


def _teams_group():
    comp = f.competition(format="teams", name="Teams test")
    stg = f.stage(comp)
    grp = f.group(stg, tier=1, rating=500)
    entries = [f.entry(comp, f.player()) for _ in range(4)]
    for e in entries:
        f.member(grp, e)
    return comp, stg, grp, entries


def test_teams_live_standings_score_sets_and_skip_absent(pg):
    comp, stg, grp, (e1, e2, e3, e4) = _teams_group()
    r1 = f.round_(stg, 1)
    m = f.match(grp, r1, home=(e1, e2), away=(e3,), sets=[(6, 2), (2, 6)], status="played")
    db.session.add(MatchSet(match_id=m.id, set_no=3, home_games=2, away_games=2, outcome="timeout_draw"))
    db.session.flush()
    db.session.expire_all()
    st = group_standings(grp.id)
    rows = {r.entry_id: r for r in st.rows}
    assert not st.frozen and st.format == "teams"
    assert (rows[e1.id].points, rows[e1.id].sets_won, rows[e1.id].sets_drawn) == (4, 1, 1)
    assert rows[e3.id].points == 4 and rows[e4.id].points == 0 and rows[e4.id].appearances == 0
    assert rows[e1.id].place == rows[e2.id].place == rows[e3.id].place == 1 and rows[e4.id].place == 4


def test_empty_group_has_rows_for_every_member(pg):
    _, _, grp, entries = _teams_group()
    st = group_standings(grp.id)
    assert len(st.rows) == 4 and {r.place for r in st.rows} == {1}


def test_frozen_legacy_group_returns_stored_rows_with_b3_fixed(pg):
    snap = StandingSnapshot.query.filter(StandingSnapshot.group_member_id.isnot(None), StandingSnapshot.source == "legacy").first()
    grp_id = snap.group_member.group_id
    st = group_standings(grp_id)
    assert st.frozen and st.format == "classica"
    assert [r.place for r in st.rows] == sorted(r.place for r in st.rows)
    assert all(r.attendance_pct is None or 0 <= r.attendance_pct <= 100 for r in st.rows)
