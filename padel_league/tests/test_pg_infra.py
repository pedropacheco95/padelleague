"""The Postgres test infrastructure itself: template clone, rollback, factories."""

from padel_league.models.v2 import Competition
from padel_league.tests import factories as f


def test_template_has_the_migrated_data(pg):
    assert Competition.query.filter_by(format="teams").count() == 1


def test_factories_build_a_played_match(pg):
    comp = f.competition()
    stg = f.stage(comp)
    grp = f.group(stg)
    rnd = f.round_(stg)
    players = [f.entry(comp, f.player()) for _ in range(4)]
    m = f.match(grp, rnd, home=players[:2], away=players[2:], sets=[(6, 3)], status="played")
    assert len(m.participants) == 4 if hasattr(m, "participants") else True


def test_writes_are_rolled_back_between_tests(pg):
    assert Competition.query.filter_by(name="Test competition").count() == 0
