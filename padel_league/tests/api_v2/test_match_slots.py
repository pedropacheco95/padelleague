"""PUT /matches/{id}/slots: take a player out of one match, name the substitute, put them back,
before and after the result (the legacy "ele não veio" control, now per match)."""

import pytest

from padel_league.models.v2 import Absence, Award, CompetitionMatch, RankingSnapshot
from padel_league.services import closeout
from padel_league.services import standings as standings_svc
from padel_league.sql_db import db
from padel_league.tests import factories as f
from padel_league.tests.api_v2.conftest import bearer, check, persist

PATH = "/matches/{matchId}/slots"


def _teams_played():
    """One Teams match already saved 6-4 3-6 2-6 (match 3554's shape): away won sets 2 and 3."""
    comp = f.competition(format="teams", name="Slots test")
    stg = f.stage(comp)
    grp = f.group(stg, rating=None)
    rnd = f.round_(stg)
    entries = [f.entry(comp, f.player()) for _ in range(4)]
    for e in entries:
        f.member(grp, e)
    m = f.match(grp, rnd, home=entries[:2], away=entries[2:], status="played", sets=[(6, 4), (3, 6), (2, 6)])
    persist()
    return grp, rnd, entries, m


def _row(grp, entry):
    return next(r for r in standings_svc.compute_rows(grp) if r.entry_id == entry.id)


def _put(client, h, m, side, slot, player_id, status=200):
    return check(
        client.put(f"/api/v2/matches/{m.id}/slots", json={"side": side, "slot": slot, "playerId": player_id}, headers=h),
        PATH, "put", status,
    )


def _seat(body, side, slot):
    return next(p for p in body["participants"] if p["side"] == side and p["slot"] == slot)


def test_take_out_after_result_then_put_back(client, make_user):
    grp, rnd, entries, m = _teams_played()
    absent = entries[2]
    sub = f.player()
    persist()
    h = bearer(make_user())
    assert (_row(grp, absent).points, _row(grp, absent).appearances) == (6, 1)

    body = _put(client, h, m, "away", 1, sub.id)
    seat = _seat(body, "away", 1)
    assert seat["role"] == "substitute" and seat["player"]["id"] == sub.id
    assert seat["replaces"]["id"] == absent.player_id
    assert [a["player"]["id"] for a in body["absences"]] == [absent.player_id]
    absence = Absence.query.filter_by(entry_id=absent.id, round_id=rnd.id).one()
    assert absence.kind == "partial" and absence.source == "recorded"
    assert (_row(grp, absent).points, _row(grp, absent).appearances) == (0, 0)
    assert _row(grp, entries[3]).points == 6  # the partner keeps the sets they won
    assert body["sets"][0]["homeGames"] == 6 and body["status"] == "played"  # the result stands

    body = _put(client, h, m, "away", 1, absent.player_id)
    seat = _seat(body, "away", 1)
    assert seat["role"] == "member" and seat["player"]["id"] == absent.player_id
    assert body["absences"] == []
    assert Absence.query.filter_by(entry_id=absent.id, round_id=rnd.id).first() is None
    assert (_row(grp, absent).points, _row(grp, absent).appearances) == (6, 1)


def test_unknown_substitute_then_named_then_changed(client, make_user):
    grp, rnd, entries, m = _teams_played()
    a, b = f.player(), f.player()
    persist()
    h = bearer(make_user())
    body = _put(client, h, m, "home", 2, None)
    assert _seat(body, "home", 2)["role"] == "unknown" and _seat(body, "home", 2)["player"] is None
    assert _seat(body, "home", 2)["replaces"]["id"] == entries[1].player_id
    body = _put(client, h, m, "home", 2, a.id)
    assert _seat(body, "home", 2)["player"]["id"] == a.id
    body = _put(client, h, m, "home", 2, b.id)
    assert _seat(body, "home", 2)["player"]["id"] == b.id
    assert _seat(body, "home", 2)["replaces"]["id"] == entries[1].player_id
    # still restorable after the substitute changed twice
    body = _put(client, h, m, "home", 2, entries[1].player_id)
    assert _seat(body, "home", 2)["role"] == "member"
    assert Absence.query.filter_by(entry_id=entries[1].id).first() is None


def test_scheduled_classica_match_partial_absence_keeps_other_matches(client, make_user):
    comp = f.competition(format="classica", name="Slots classica")
    stg = f.stage(comp)
    grp = f.group(stg)
    rnd = f.round_(stg)
    entries = [f.entry(comp, f.player()) for _ in range(4)]
    for e in entries:
        f.member(grp, e)
    m1 = f.match(grp, rnd, home=entries[:2], away=entries[2:])
    m2 = f.match(grp, rnd, home=[entries[0], entries[2]], away=[entries[1], entries[3]])
    persist()
    h = bearer(make_user())
    _put(client, h, m1, "home", 1, None)
    other = check(client.get(f"/api/v2/matches/{m2.id}"), "/matches/{matchId}")
    assert _seat(other, "home", 1)["player"]["id"] == entries[0].player_id
    absence = Absence.query.filter_by(entry_id=entries[0].id).one()
    assert absence.kind == "partial"


def test_refusals(client, make_user):
    grp, rnd, entries, m = _teams_played()
    outsider = f.player()
    persist()
    h = bearer(make_user())
    assert client.put(f"/api/v2/matches/{m.id}/slots", json={"side": "home", "slot": 1, "playerId": None}).status_code == 401
    body = _put(client, h, m, "home", 1, entries[3].player_id, status=400)
    assert body["code"] == "already_in_match"
    _put(client, h, m, "home", 1, None)
    # entries[0] is out; another group member can't take the seat as a substitute
    comp_member = f.entry(grp.stage.competition, f.player())
    f.member(grp, comp_member)
    persist()
    assert _put(client, h, m, "home", 1, comp_member.player_id, status=400)["code"] == "substitute_is_member"
    assert _put(client, h, m, "left", 1, None, status=400)["code"] == "invalid_slot"
    assert _put(client, h, m, "home", 1, 999999, status=400)["code"] == "player_not_found"
    assert check(client.put("/api/v2/matches/999999/slots", json={"side": "home", "slot": 1}, headers=h), PATH, "put", 404)
    grp.has_ended = True
    persist()
    assert _put(client, h, m, "home", 2, outsider.id, status=409)["code"] == "group_closed"


def test_undo_absence_after_result_restores_member(client, make_user):
    grp, rnd, entries, m = _teams_played()
    sub = f.player()
    persist()
    h = bearer(make_user())
    resp = client.post(
        f"/api/v2/rounds/{rnd.id}/absences",
        json={"playerId": entries[2].player_id, "groupId": grp.id, "substitutePlayerId": sub.id},
        headers=h,
    )
    assert resp.status_code == 201
    assert _row(grp, entries[2]).points == 0
    assert client.delete(f"/api/v2/absences/{resp.get_json()['id']}", headers=h).status_code == 204
    body = check(client.get(f"/api/v2/matches/{m.id}"), "/matches/{matchId}")
    assert _seat(body, "away", 1)["player"]["id"] == entries[2].player_id
    assert _row(grp, entries[2]).points == 6


def test_closed_group_take_out_refreshes_awards_and_ranking(client, make_user):
    from padel_league.tests.domain.test_closeout_service import _teams_reference_group

    comp, grp, e = _teams_reference_group()
    event = closeout.close_group(grp.id)
    persist()
    before = {a.entry_id: a.total for a in Award.query.filter_by(award_event_id=event.id)}
    j3 = [x for x in CompetitionMatch.query.filter_by(group_id=grp.id) if x.round.number == 3]
    ad = next(x for x in j3 if any(p.entry_id == e[1].id for p in x.participants))
    seat = next(p for p in ad.participants if p.entry_id == e[1].id)
    sub = f.player()
    persist()
    _put(client, bearer(make_user(role="admin")), ad, seat.side, seat.slot, sub.id)
    db.session.expire_all()
    after = {a.entry_id: a.total for a in Award.query.filter_by(award_event_id=event.id)}
    assert after[e[1].id] < before[e[1].id]
    snap = RankingSnapshot.query.order_by(RankingSnapshot.id.desc()).first()
    assert {r.player_id: r.points for r in snap.entries}[e[1].player_id] == pytest.approx(after[e[1].id])


def test_partial_absence_not_listed_on_the_other_pairs_match(client, make_user):
    """Teams: the division's other match of the jornada doesn't list a player taken out of this one."""
    comp = f.competition(format="teams", name="Slots other match")
    stg = f.stage(comp)
    grp = f.group(stg, rating=None)
    rnd = f.round_(stg)
    entries = [f.entry(comp, f.player()) for _ in range(8)]
    for e in entries:
        f.member(grp, e)
    m1 = f.match(grp, rnd, home=entries[:2], away=entries[2:4], status="played", sets=[(6, 4), (3, 6), (2, 6)])
    m2 = f.match(grp, rnd, home=entries[4:6], away=entries[6:])
    persist()
    body = _put(client, bearer(make_user()), m1, "home", 1, None)
    assert [a["player"]["id"] for a in body["absences"]] == [entries[0].player_id]
    other = check(client.get(f"/api/v2/matches/{m2.id}"), "/matches/{matchId}")
    assert other["absences"] == []
