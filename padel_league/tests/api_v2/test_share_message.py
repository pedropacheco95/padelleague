"""Teams WhatsApp jornada message button (Pedro and Dudas, 2 Nov): the weekly window (Wednesday 00:01
Europe/Lisbon), the jornada it offers, and the copied state shared by every admin."""

from datetime import date, datetime, timedelta

import pytest

from padel_league.domain.errors import Conflict
from padel_league.models.v2 import AuditEvent
from padel_league.services import share_message
from padel_league.sql_db import db
from padel_league.tests import factories as f
from padel_league.tests.api_v2.conftest import bearer, check, persist

PATH = "/competitions/{competitionId}/share-message"


def _start(utc):
    return share_message.window_start(utc)


# --- the window boundary ------------------------------------------------------------------------


def test_window_boundary_in_a_winter_week():
    # Lisbon = UTC+0 in November.
    tue_2359 = datetime(2026, 11, 10, 23, 59)
    wed_0000 = datetime(2026, 11, 11, 0, 0, 30)
    wed_0001 = datetime(2026, 11, 11, 0, 1)
    assert _start(tue_2359).date() == date(2026, 11, 4)
    assert _start(wed_0000).date() == date(2026, 11, 4)  # 00:00 still belongs to last week
    assert _start(wed_0001).date() == date(2026, 11, 11)
    assert (_start(wed_0001).hour, _start(wed_0001).minute) == (0, 1)
    assert _start(wed_0001).utcoffset() == timedelta(0)


def test_window_boundary_in_the_week_clocks_go_back():
    # Clocks went back on Sunday 25 Oct 2026: the window that opened on Wed 21 Oct did so at UTC+1.
    tue_2359 = datetime(2026, 10, 27, 23, 59)  # Lisbon 23:59 (UTC+0 by now)
    start = _start(tue_2359)
    assert start.date() == date(2026, 10, 21) and start.utcoffset() == timedelta(hours=1)
    assert start.astimezone(share_message.timezone.utc).replace(tzinfo=None) == datetime(2026, 10, 20, 23, 1)
    wed = _start(datetime(2026, 10, 28, 0, 1))
    assert wed.date() == date(2026, 10, 28) and wed.utcoffset() == timedelta(0)


def test_window_boundary_in_the_week_clocks_go_forward():
    # Clocks went forward on Sunday 29 Mar 2026: Wed 1 Apr 00:01 Lisbon is Tue 31 Mar 23:01 UTC.
    assert _start(datetime(2026, 3, 31, 22, 59)).date() == date(2026, 3, 25)  # Tue 23:59 Lisbon
    assert _start(datetime(2026, 3, 31, 23, 0, 30)).date() == date(2026, 3, 25)  # Wed 00:00 Lisbon
    opened = _start(datetime(2026, 3, 31, 23, 1))  # Wed 00:01 Lisbon
    assert opened.date() == date(2026, 4, 1) and opened.utcoffset() == timedelta(hours=1)


# --- the jornada a window offers ----------------------------------------------------------------


def _teams(dates=(date(2026, 10, 20), date(2026, 10, 27), date(2026, 11, 3)), mt2_matches=True):
    """MT1: three rounds (dated as given, None = undated), one match each. MT2: one undated round."""
    comp = f.competition(format="teams", name="Share message test")
    stg = f.stage(comp, number=1)
    grp = f.group(stg)
    entries = [f.entry(comp, f.player()) for _ in range(4)]
    for e in entries:
        f.member(grp, e)
    rounds, matches = [], []
    for n, on in enumerate(dates, start=1):
        r = f.round_(stg, number=n)
        r.date = on
        rounds.append(r)
        matches.append(f.match(grp, r, home=entries[:2], away=entries[2:]))
    stg2 = f.stage(comp, number=2)
    r2 = f.round_(stg2, number=1)
    r2.date = None
    if mt2_matches:
        grp2 = f.group(stg2)
        for e in entries:
            f.member(grp2, e)
        f.match(grp2, r2, home=entries[:2], away=entries[2:])
    persist()
    return comp, rounds, matches, r2


def _offered(comp, wednesday):
    target = share_message.window_round(comp.id, datetime.combine(wednesday, share_message.OPENS_AT, tzinfo=share_message.LISBON))
    return target and target["round"]


def test_dated_rounds_follow_the_calendar(pg):
    comp, rounds, matches, mt2 = _teams()
    assert _offered(comp, date(2026, 10, 14)) == rounds[0]
    assert _offered(comp, date(2026, 10, 28)) == rounds[2]  # prod on 2 Nov: jornada 3 (3 Nov)
    # Wed 4 Nov: jornada 3 is behind by date even with its result still missing (no re-offer).
    assert matches[2].status == "scheduled"
    assert _offered(comp, date(2026, 11, 4)) == mt2


def test_undated_rounds_follow_results(pg):
    comp, rounds, matches, _ = _teams(dates=(None, None, None))
    assert _offered(comp, date(2026, 10, 28)) == rounds[0]
    matches[0].status = "played"
    persist()
    assert _offered(comp, date(2026, 10, 28)) == rounds[1]


def test_scheduled_time_dates_an_undated_round(pg):
    comp, rounds, matches, _ = _teams(dates=(None, None, None))
    matches[0].scheduled_at = datetime(2026, 10, 20, 20, 30)  # 21:30 Lisbon summer time
    persist()
    assert _offered(comp, date(2026, 10, 28)) == rounds[1]


def test_next_mini_torneio_without_matches_offers_nothing(pg):
    comp, _rounds, _matches, _ = _teams(mt2_matches=False)
    assert _offered(comp, date(2026, 11, 4)) is None


# --- copied state, shared by admins -------------------------------------------------------------


def test_copy_is_shared_between_admins_and_admin_only(client, make_user):
    comp, rounds, _matches, _ = _teams(dates=(None, None, None))  # undated: offers round 1 any day
    pedro, dudas, player = make_user(role="admin"), make_user(role="admin"), make_user()
    url = f"/api/v2/competitions/{comp.id}/share-message"
    check(client.get(url, headers=bearer(player)), PATH, "get", 403)
    check(client.post(url, json={"roundId": rounds[0].id}, headers=bearer(player)), PATH, "post", 403)
    check(client.get(url), PATH, "get", 401)

    before = check(client.get(url, headers=bearer(dudas)), PATH)
    assert before["round"]["id"] == rounds[0].id and before["round"]["number"] == 1
    assert before["copied"] is False and before["copiedBy"] is None

    body = check(client.post(url, json={"roundId": rounds[0].id}, headers=bearer(pedro)), PATH, "post")
    assert body["copied"] is True and body["copiedBy"]["id"] == pedro.id and body["copiedAt"]
    seen = check(client.get(url, headers=bearer(dudas)), PATH)
    assert seen["copied"] is True and seen["copiedBy"]["username"] == pedro.username
    # a second copy in the same window keeps the first record
    check(client.post(url, json={"roundId": rounds[0].id}, headers=bearer(dudas)), PATH, "post")
    assert AuditEvent.query.filter_by(entity="competition", entity_id=comp.id, action="share_copied").count() == 1


def test_stale_round_and_other_formats_are_refused(client, make_user):
    comp, rounds, _matches, _ = _teams(dates=(None, None, None))
    admin = bearer(make_user(role="admin"))
    url = f"/api/v2/competitions/{comp.id}/share-message"
    resp = check(client.post(url, json={"roundId": rounds[1].id}, headers=admin), PATH, "post", 409)
    assert resp["code"] == "share_round_changed"
    check(client.post(url, json={}, headers=admin), PATH, "post", 400)
    classica = f.competition(format="classica", name="Not teams")
    persist()
    resp = client.get(f"/api/v2/competitions/{classica.id}/share-message", headers=admin)
    assert resp.status_code == 409 and resp.get_json()["code"] == "not_teams"


def test_copy_hides_the_button_only_until_the_next_window(pg):
    comp, rounds, _matches, _ = _teams(dates=(None, None, None))
    tuesday = datetime(2026, 11, 10, 22, 0)
    share_message.record_copy(comp.id, rounds[0].id, actor_user_id=None, now=tuesday)
    assert share_message.state(comp.id, tuesday + timedelta(hours=1, minutes=59))["copy"] is not None  # Tue 23:59
    nxt = share_message.state(comp.id, datetime(2026, 11, 11, 0, 1))  # Wed 00:01: new window
    assert nxt["target"]["round"] == rounds[0] and nxt["copy"] is None
    with pytest.raises(Conflict):
        share_message.record_copy(comp.id, rounds[2].id, actor_user_id=None, now=tuesday)
    db.session.rollback()
