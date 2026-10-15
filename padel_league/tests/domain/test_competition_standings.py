"""Competition-level standings: Teams edition total, Shuffle overall (Postgres, rolled back)."""

from padel_league.services import closeout, results
from padel_league.services.standings import competition_standings
from padel_league.sql_db import db
from padel_league.tests import factories as f


def test_shuffle_overall_matches_stored_positions_and_compat_points(pg):
    st = competition_standings(26)
    assert st.format == "shuffle" and len(st.rows) == 48
    assert [r.place for r in st.rows] == list(range(1, 49))
    compat = dict(
        db.session.execute(db.text("select player_id, points from compat.players_in_shuffle_tournament")).all()
    )
    assert {r.player_id: r.points for r in st.rows} == compat


def test_teams_edition_total_sums_closed_mini_tournaments(pg):
    comp = f.competition(format="teams", name="Teams edition")
    players = [f.player() for _ in range(2)]
    entries = [f.entry(comp, p) for p in players]
    for number in (1, 2):
        stg = f.stage(comp, number=number)
        grp = f.group(stg, tier=number, rating=None)
        for e in entries:
            f.member(grp, e)
        m = f.match(grp, f.round_(stg, 1), home=(entries[0],), away=(entries[1],))
        results.record_sets(m.id, [{"home_games": 6, "away_games": 1}] * 3)
        db.session.flush()
        closeout.close_group(grp.id, recompute_ranking=False)
    rows = {r.entry_id: r for r in competition_standings(comp.id).rows}
    winner = rows[entries[0].id]
    # stage 1 tier 1: 500 + 3·5; stage 2 tier 2: 250 + 3·2.5
    assert winner.points == 500 + 15 + 250 + 7.5 and winner.place == 1
    assert (winner.appearances, winner.sets_won) == (2, 6)
    assert [s["stage_number"] for s in winner.stages] == [1, 2]
    assert rows[entries[1].id].points == int(500 * 0.75) + int(250 * 0.75)
