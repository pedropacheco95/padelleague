"""Teams results saved set by set (Pedro, Oct 2026): 1–2 completed sets are stored and
shown to everyone, but count for nothing (standings, close-out, awards) until the 3rd
set completes the match. Stored as status 'scheduled' + match_sets rows: no schema change."""

from padel_league.models.v2 import Absence, CompetitionGroup, MatchParticipant
from padel_league.services import closeout
from padel_league.services import standings as standings_svc
from padel_league.sql_db import db
from padel_league.tests import factories as f
from padel_league.tests.api_v2.conftest import bearer, check, persist

PATH = "/matches/{matchId}/result"


def _teams_group(n_matches=1):
    comp = f.competition(format="teams", name="Set-by-set test")
    stg = f.stage(comp, emits_award=True)
    grp = f.group(stg, rating=500)
    rnd = f.round_(stg)
    entries = [f.entry(comp, f.player()) for _ in range(4)]
    for e in entries:
        f.member(grp, e)
    matches = [f.match(grp, rnd, home=entries[:2], away=entries[2:]) for _ in range(n_matches)]
    persist()
    return grp, rnd, entries, matches


def _put(client, h, m, sets, status=200):
    body = {"sets": [{"homeGames": a, "awayGames": b, "outcome": o} for a, b, o in sets]}
    return check(client.put(f"/api/v2/matches/{m.id}/result", json=body, headers=h), PATH, "put", status)


def _rows(grp):
    return {r.entry_id: (r.points, r.appearances) for r in standings_svc.compute_rows(grp)}


def _absences(entries):
    return Absence.query.filter(Absence.entry_id.in_([e.id for e in entries])).count()


def _seats(m):
    return sorted((p.side, p.slot, p.role, p.player_id) for p in MatchParticipant.query.filter_by(match_id=m.id))


def test_partial_sets_saved_shown_and_not_counted_until_complete(client, make_user):
    grp, rnd, entries, (m,) = _teams_group()
    h = bearer(make_user())
    seats_before = _seats(m)

    # set 1 now: stored, status unchanged, nothing counts it
    body = _put(client, h, m, [(6, 4, "completed")])
    assert body["status"] == "scheduled" and body["inProgress"] is True
    assert [(s["setNo"], s["homeGames"], s["awayGames"]) for s in body["sets"]] == [(1, 6, 4)]
    assert body["homeScore"] is None and body["winner"] is None
    assert all(v == (0, 0) for v in _rows(grp).values())
    assert not closeout.is_complete(grp.id) and not db.session.get(CompetitionGroup, grp.id).has_ended
    assert _seats(m) == seats_before and _absences(entries) == 0

    # visible to everyone who opens the match or the jornada (no login)
    shown = check(client.get(f"/api/v2/matches/{m.id}"), "/matches/{matchId}")
    assert shown["inProgress"] is True and len(shown["sets"]) == 1
    listed = check(client.get(f"/api/v2/groups/{grp.id}/matches"), "/groups/{groupId}/matches")
    assert listed[0]["inProgress"] is True and listed[0]["status"] == "scheduled" and len(listed[0]["sets"]) == 1

    # set 2 later: still in progress
    body = _put(client, h, m, [(6, 4, "completed"), (3, 6, "completed")])
    assert body["status"] == "scheduled" and body["inProgress"] is True and len(body["sets"]) == 2
    assert all(v == (0, 0) for v in _rows(grp).values())

    # set 3 completes the match: counted, and the group (one match) closes with awards
    body = _put(client, h, m, [(6, 4, "completed"), (3, 6, "completed"), (6, 2, "completed")])
    assert body["status"] == "played" and body["inProgress"] is False
    assert (body["homeScore"], body["awayScore"], body["winner"]) == (6, 3, "home")
    rows = _rows(grp)
    assert rows[entries[0].id] == (6, 1) and rows[entries[2].id] == (3, 1)
    assert closeout.is_complete(grp.id)
    assert db.session.get(CompetitionGroup, grp.id).has_ended is True
    assert _seats(m) == seats_before and _absences(entries) == 0


def test_partial_set_rejections(client, make_user):
    grp, rnd, entries, (m,) = _teams_group()
    h = bearer(make_user())
    assert _put(client, h, m, [], 400)["code"] == "teams_needs_three_sets"
    # a time-out chain is always the full 3 sets
    assert _put(client, h, m, [(3, 2, "timeout_draw")], 400)["code"] == "teams_needs_three_sets"
    assert _put(client, h, m, [(6, 4, "completed"), (5, 5, "completed")], 400)["code"] == "invalid_set_score"
    assert _put(client, h, m, [(6, 4, "completed")] * 4, 400)["code"] == "invalid_input"
    # Clássica / Shuffle keep the one-set rule
    comp = f.competition(format="classica", name="One set")
    stg = f.stage(comp)
    cg = f.group(stg, rating=None)
    cr = f.round_(stg)
    ce = [f.entry(comp, f.player()) for _ in range(4)]
    for e in ce:
        f.member(cg, e)
    cm = f.match(cg, cr, home=ce[:2], away=ce[2:])
    persist()
    assert _put(client, h, cm, [(6, 4, "completed"), (6, 4, "completed")], 400)["code"] == "one_set_expected"


def test_partial_keeps_seats_and_absences(client, make_user):
    """Saving a set never touches who played: a substitute already in a seat stays, the
    absence stays, and the member still scores nothing."""
    grp, rnd, entries, (m,) = _teams_group()
    sub = f.player()
    persist()
    h = bearer(make_user())
    check(
        client.put(f"/api/v2/matches/{m.id}/slots", json={"side": "away", "slot": 1, "playerId": sub.id}, headers=h),
        "/matches/{matchId}/slots", "put",
    )
    seats = _seats(m)
    assert ("away", 1, "substitute", sub.id) in seats and _absences(entries) == 1
    body = _put(client, h, m, [(6, 4, "completed")])
    assert body["inProgress"] is True
    assert _seats(m) == seats and _absences(entries) == 1
    assert all(v == (0, 0) for v in _rows(grp).values())


def test_delete_clears_a_partial_result(client, make_user):
    grp, rnd, entries, (m,) = _teams_group()
    h = bearer(make_user())
    _put(client, h, m, [(6, 4, "completed")])
    body = check(client.delete(f"/api/v2/matches/{m.id}/result", headers=h), PATH, "delete")
    assert body["status"] == "scheduled" and body["sets"] == [] and body["inProgress"] is False


def test_closed_group_refuses_a_partial_result(client, make_user):
    """An ended group's results belong to the admins, and only complete ones: a partial
    save would un-count the match and rewrite its awards."""
    grp, rnd, entries, (m,) = _teams_group()
    h = bearer(make_user(role="admin"))
    _put(client, h, m, [(6, 4, "completed"), (3, 6, "completed"), (6, 2, "completed")])
    assert db.session.get(CompetitionGroup, grp.id).has_ended is True
    assert _put(client, h, m, [(6, 4, "completed")], 409)["code"] == "group_closed"
    shown = check(client.get(f"/api/v2/matches/{m.id}"), "/matches/{matchId}")
    assert shown["status"] == "played" and len(shown["sets"]) == 3
