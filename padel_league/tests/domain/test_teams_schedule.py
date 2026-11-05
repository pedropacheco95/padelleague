"""Teams on its own: dated jornadas, the pair choice opening when a mini-tournament
ends, and the pairs and divisions closing after the deadline."""

from datetime import date, datetime

from padel_league.domain.teams_calendar import pairing_deadline, round_date
from padel_league.models.v2 import CompetitionGroup, CompetitionMatch, Round, Stage
from padel_league.services import closeout, ranking, results, teams_pairing, teams_schedule
from padel_league.sql_db import db
from padel_league.tests.domain.test_teams_divisions import _teams_stage1

START = date(2026, 10, 20)
AFTER_MT1 = datetime(2026, 11, 4, 13, 0)


def test_the_start_date_defines_every_jornada():
    assert [round_date(START, 1, n, 3) for n in (1, 2, 3)] == [date(2026, 10, 20), date(2026, 10, 27), date(2026, 11, 3)]
    assert [round_date(START, 2, n, 3) for n in (1, 2, 3)] == [date(2026, 11, 10), date(2026, 11, 17), date(2026, 11, 24)]
    assert round_date(START, 4, 3, 3) == date(2027, 1, 5)


def test_deadline_is_the_sunday_before_at_midnight_lisbon():
    assert pairing_deadline(date(2026, 11, 10), AFTER_MT1) == datetime(2026, 11, 8, 23, 59, 59)  # winter: UTC
    assert pairing_deadline(date(2026, 10, 20), datetime(2026, 10, 1)) == datetime(2026, 10, 18, 22, 59, 59)  # summer: UTC+1


def test_a_late_finish_still_leaves_the_next_day():
    assert pairing_deadline(date(2026, 11, 10), datetime(2026, 11, 9, 12, 0)) == datetime(2026, 11, 10, 23, 59, 59)


def _play(group):
    for m in CompetitionMatch.query.filter_by(group_id=group.id):
        results.record_sets(m.id, [{"home_games": 6, "away_games": 3}] * 2 + [{"outcome": "timeout_draw"}])
    db.session.flush()


def _stage(comp, number):
    return Stage.query.filter_by(competition_id=comp.id, number=number).one()


def test_a_whole_mini_tournament_on_its_own(pg):
    comp, stage = _teams_stage1()
    comp.starts_on = START
    ranking.bootstrap()
    db.session.commit()

    # before the deadline nothing happens
    assert teams_schedule.run_due(datetime(2026, 10, 18, 22, 0)) == []
    assert not stage.pairing_closed

    # after it the pairs close and the divisions form, with their dates
    lines = teams_schedule.run_due(datetime(2026, 10, 19, 0, 1))
    assert len(lines) == 2 and stage.pairing_closed and stage.status == "running"
    assert len(teams_pairing.stage_pairs(stage)) == 24
    groups = CompetitionGroup.query.filter_by(stage_id=stage.id).order_by(CompetitionGroup.tier).all()
    assert len(groups) == 6
    dates = [r.date for r in Round.query.filter_by(stage_id=stage.id).order_by(Round.number)]
    assert dates == [date(2026, 10, 20), date(2026, 10, 27), date(2026, 11, 3)]
    assert teams_schedule.run_due(datetime(2026, 10, 19, 1, 1)) == []  # idempotent

    # the next pair choice opens with the last group of the mini-tournament, not before
    following = _stage(comp, 2)
    for group in groups[:-1]:
        _play(group)
        closeout.close_group(group.id, now=AFTER_MT1, recompute_ranking=False)
    assert following.pairing_deadline is None
    _play(groups[-1])
    closeout.close_group(groups[-1].id, now=AFTER_MT1, recompute_ranking=False)
    assert stage.status == "ended"
    assert following.pairing_deadline == datetime(2026, 11, 8, 23, 59, 59)
    assert _stage(comp, 3).pairing_deadline is None
    assert teams_pairing.current_mini_tournament().id == following.id


def test_the_tick_opens_what_an_ended_mini_tournament_left_closed(pg):
    comp, stage = _teams_stage1()
    comp.starts_on = START
    stage.status = "ended"
    stage.pairing_closed = True
    db.session.commit()
    assert len(teams_schedule.run_due(AFTER_MT1)) == 1
    assert _stage(comp, 2).pairing_deadline == datetime(2026, 11, 8, 23, 59, 59)
    assert teams_schedule.run_due(AFTER_MT1) == []
