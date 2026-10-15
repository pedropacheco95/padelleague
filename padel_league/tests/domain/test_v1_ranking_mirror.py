"""v1 ranking page after bootstrap: a position-0 player must not bring back the old rule."""

from padel_league.models import League, Player
from padel_league.models.v2 import AwardEvent, RankingSnapshot
from padel_league.services import ranking
from padel_league.sql_db import db


def _v1_ranking():
    return [(p.id, p.ranking_points, p.ranking_position) for p in League.query.first().players_rankings_position()]


def test_position_zero_player_keeps_the_v2_ranking(pg):
    ranking.bootstrap()
    db.session.commit()
    expected = _v1_ranking()
    assert expected[0][1] == 5371  # Pi Magalhaes under the 2026/27 rule, not the old 4484

    played = {p.id for p in League.query.first().all_players_that_played()}
    victim = Player.query.filter(Player.id.in_(played)).order_by(Player.id).first()
    victim.ranking_position = 0
    db.session.commit()

    assert _v1_ranking() == expected


def test_before_bootstrap_the_old_rule_still_runs(pg):
    # back to the pre-bootstrap state: only the imported legacy snapshot
    events = [e.id for e in AwardEvent.query.filter_by(competition_id=26)]
    RankingSnapshot.query.filter(RankingSnapshot.rule_id != 1).delete(synchronize_session=False)
    for e in AwardEvent.query.filter(AwardEvent.id.in_(events)):
        db.session.delete(e)
    db.session.flush()
    assert not ranking.is_bootstrapped(1)
    League.query.first().update_rankings()
    pi = Player.query.filter_by(name="Pi Magalhaes").first()
    assert pi.ranking_points == 4484  # old last-4-by-id rule
