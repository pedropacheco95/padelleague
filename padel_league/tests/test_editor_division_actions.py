"""Editor replace-player / readd-player write v2 rows (no compat writes)."""

import random
from collections import Counter
from datetime import datetime

from padel_league.models import Division
from padel_league.models.v2 import Absence, AuditEvent, CompetitionMatch, Entry
from padel_league.services.fixtures import generate_group_fixtures
from padel_league.services.results import mark_absent
from padel_league.sql_db import db
from padel_league.tests import factories as f


def _group():
    stage = f.stage(f.competition(name=f"Editor {datetime.utcnow().timestamp()}"))
    grp = f.group(stage, starts_at=datetime(2026, 11, 3, 21, 30))
    players = [f.player() for _ in range(8)]
    for plr in players:
        f.member(grp, f.entry(stage.competition, plr))
    db.session.expire(grp, ["members"])
    generate_group_fixtures(grp, rng=random.Random(3), commit=False)
    return grp, players


def _admin_client(app):
    # Flask-Session has no backend in the test config; signed cookies are enough here.
    from flask.sessions import SecureCookieSessionInterface

    app.session_interface = SecureCookieSessionInterface()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True
    return client


def _first_match_of(grp, player):
    matches = CompetitionMatch.query.filter_by(group_id=grp.id).join(CompetitionMatch.round).filter_by(number=1)
    return next(m for m in matches.order_by(CompetitionMatch.id) if any(p.player_id == player.id for p in m.participants))


def _appearances(grp):
    c = Counter()
    for m in CompetitionMatch.query.filter_by(group_id=grp.id):
        c.update(p.player_id for p in m.participants)
    return c


def test_replace_player_moves_member_matches_and_keeps_the_old_entry(pg):
    grp, players = _group()
    a, b = players[0], f.player()
    r = _admin_client(pg).post(
        f"/editor/division/{grp.id}/replace-player", data={"player_a_id": a.id, "player_b_id": b.id}
    )
    assert r.status_code == 302, r.get_data(as_text=True)[:500]

    db.session.expire_all()
    counts = _appearances(grp)
    assert counts[a.id] == 0 and counts[b.id] == 21
    assert sorted(m.entry.player_id for m in grp.members) == sorted([b.id] + [p.id for p in players[1:]])
    comp_id = grp.stage.competition_id
    assert Entry.query.filter_by(competition_id=comp_id, player_id=a.id).one().status == "replaced"
    assert AuditEvent.query.filter_by(entity="group", entity_id=grp.id, action="replace_player").count() == 1
    # v1 reads (compat views) see B in the roster and every match
    division = Division.query.get(grp.id)
    assert b.id in {rel.player_id for rel in division.players_relations}
    assert a.id not in {rel.player_id for m in division.matches for rel in m.players_relations}


def test_replace_player_refuses_a_player_outside_the_division(pg):
    grp, players = _group()
    outsider, b = f.player(), f.player()
    r = _admin_client(pg).post(
        f"/editor/division/{grp.id}/replace-player", data={"player_a_id": outsider.id, "player_b_id": b.id}
    )
    assert r.status_code == 200
    assert "não pertence" in r.get_data(as_text=True)
    assert _appearances(grp)[b.id] == 0


def test_readd_player_undoes_an_absence(pg):
    grp, players = _group()
    a = players[0]
    first = _first_match_of(grp, a)
    partner_id = next(
        p.player_id for p in first.participants
        if p.side == next(q.side for q in first.participants if q.player_id == a.id) and p.player_id != a.id
    )
    mark_absent(grp.id, 1, a.id)
    db.session.flush()
    assert _appearances(grp)[a.id] == 18
    assert Absence.query.join(Entry).filter(Entry.player_id == a.id).count() == 1

    r = _admin_client(pg).post(
        f"/editor/division/{grp.id}/readd-player", data={"player_id": a.id, "partner_id": partner_id, "matchweek": 1}
    )
    assert r.status_code == 302, r.get_data(as_text=True)[:500]
    db.session.expire_all()
    # pairs are fixed within a jornada, so A is back in all three matches
    assert _appearances(grp)[a.id] == 21
    assert Absence.query.join(Entry).filter(Entry.player_id == a.id).count() == 0


def test_readd_player_takes_the_slot_back_from_a_substitute(pg):
    grp, players = _group()
    a, sub = players[0], f.player()
    first = _first_match_of(grp, a)
    side = next(p.side for p in first.participants if p.player_id == a.id)
    partner_id = next(p.player_id for p in first.participants if p.side == side and p.player_id != a.id)
    mark_absent(grp.id, 1, a.id, substitute_player_id=sub.id)
    db.session.flush()

    r = _admin_client(pg).post(
        f"/editor/division/{grp.id}/readd-player", data={"player_id": a.id, "partner_id": partner_id, "matchweek": 1}
    )
    assert r.status_code == 302
    db.session.expire_all()
    match = db.session.get(CompetitionMatch, first.id)
    assert sorted((p.side, p.role) for p in match.participants) == [
        ("away", "member"), ("away", "member"), ("home", "member"), ("home", "member")
    ]
    assert a.id in {p.player_id for p in match.participants}
    assert _appearances(grp)[sub.id] == 0
