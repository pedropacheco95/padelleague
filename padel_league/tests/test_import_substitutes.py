"""SUBS_ import: substitute slots, new external players, merges (pg, no compat writes)."""

import random
from datetime import datetime

import pytest
from sqlalchemy import text

from padel_league.models import Player, User
from padel_league.models.v2 import AuditEvent, CompetitionMatch, Entry, MatchParticipant
from padel_league.services.fixtures import generate_group_fixtures
from padel_league.services.imports import substitutes as subs
from padel_league.services.results import mark_absent
from padel_league.services.standings import compute_rows
from padel_league.sql_db import db
from padel_league.tests import factories as f


def _group():
    stage = f.stage(f.competition(name=f"Subs {datetime.utcnow().timestamp()}"))
    grp = f.group(stage, tier=1, starts_at=datetime(2026, 11, 3, 21, 30))
    players = [f.player() for _ in range(8)]
    for plr in players:
        f.member(grp, f.entry(stage.competition, plr))
    db.session.expire(grp, ["members"])
    generate_group_fixtures(grp, rng=random.Random(5), commit=False)
    return grp, players


def _partner(grp, player):
    match = (CompetitionMatch.query.filter_by(group_id=grp.id).join(CompetitionMatch.round).filter_by(number=1)
             .filter(CompetitionMatch.participants.any(MatchParticipant.player_id == player.id)).first())
    side = next(p.side for p in match.participants if p.player_id == player.id)
    return next(p.player_id for p in match.participants if p.side == side and p.player_id != player.id)


def _setup(new_name="Sub Externo Teste"):
    grp, players = _group()
    a = players[0]
    partner = db.session.get(Player, _partner(grp, a))
    mark_absent(grp.id, 1, a.id)
    db.session.flush()
    row = {"competition_id": grp.stage.competition_id, "division": 1, "jornada": 1, "replaced": a.name,
           "partner": partner.name, "sub": new_name, "points": 0}
    names = {a.name: {"resolution": "PLAYER", "ids": str(a.id)},
             partner.name: {"resolution": "PLAYER", "ids": str(partner.id)},
             new_name: {"resolution": "NEW", "ids": ""}}
    return grp, a, partner, row, names


def _subs_in(grp):
    return (MatchParticipant.query.join(CompetitionMatch, CompetitionMatch.id == MatchParticipant.match_id)
            .filter(CompetitionMatch.group_id == grp.id, MatchParticipant.role == "substitute").all())


def test_fills_the_seat_beside_the_partner_with_a_new_external_player(pg):
    grp, a, partner, row, names = _setup()
    before = compute_rows(grp)
    report = subs.run([row], names, {}, dry_run=False)
    assert (report["rows_imported"], report["participants_written"]) == (1, 3)
    assert report["players_created"] == ["Sub Externo Teste"]

    sub = Player.query.filter_by(full_name="Sub Externo Teste").one()
    status = db.session.execute(text("select status from players where id = :i"), {"i": sub.id}).scalar()
    assert status == "external"
    assert User.query.filter_by(player_id=sub.id).one().username == "subexternoteste"
    rows = _subs_in(grp)
    assert len(rows) == 3 and {r.player_id for r in rows} == {sub.id} and all(r.entry_id is None for r in rows)
    for r in rows:  # beside the partner
        assert any(p.player_id == partner.id and p.side == r.side for p in r.match.participants)
    assert compute_rows(grp) == before
    event = AuditEvent.query.filter_by(action="substitute_imported").order_by(AuditEvent.id.desc()).first()
    assert event.after["substitute_player_id"] == sub.id and len(event.after["match_participant_ids"]) == 3


def test_dry_run_writes_nothing(pg):
    grp, _, _, row, names = _setup("Sub Dry Run")
    report = subs.run([row], names, {}, dry_run=True)
    assert report["rows_imported"] == 1
    assert Player.query.filter_by(full_name="Sub Dry Run").first() is None
    assert _subs_in(grp) == []


def test_unknown_substitute_and_skip_decisions_leave_the_slot_empty(pg):
    grp, _, _, row, names = _setup()
    names["Sub Externo Teste"] = {"resolution": "UNKNOWN_SUB", "ids": ""}
    report = subs.run([row, dict(row)], names, {2: {"action": "skip", "value": "", "reason": "test"}}, dry_run=False)
    assert report["rows_imported"] == 0 and len(report["rows_skipped"]) == 2
    assert _subs_in(grp) == []


def test_a_row_without_an_absence_is_skipped(pg):
    grp, players = _group()
    names = {players[0].name: {"resolution": "PLAYER", "ids": str(players[0].id)},
             "X": {"resolution": "NEW", "ids": ""}}
    row = {"competition_id": grp.stage.competition_id, "division": 1, "jornada": 1, "replaced": players[0].name,
           "partner": "-", "sub": "X", "points": 0}
    report = subs.run([row], names, {}, dry_run=False)
    assert "no absence" in report["rows_skipped"][0][1]


def test_note_rows_record_the_substitute_without_touching_the_matches(pg):
    grp, players = _group()
    other = f.player()
    names = {players[0].name: {"resolution": "PLAYER", "ids": str(players[0].id)},
             other.name: {"resolution": "PLAYER", "ids": str(other.id)}}
    row = {"competition_id": grp.stage.competition_id, "division": 1, "jornada": 2, "replaced": players[0].name,
           "partner": "-", "sub": other.name, "points": 0}
    report = subs.run([row], names, {1: {"action": "note", "value": "", "reason": "seat kept"}}, dry_run=False)
    assert report["rows_noted"] == 1 and _subs_in(grp) == []
    event = AuditEvent.query.filter_by(action="substitute_note").order_by(AuditEvent.id.desc()).first()
    assert event.after["played_by_player_id"] == other.id


def test_merge_players_repoints_history_and_drops_the_duplicate_login(pg):
    from padel_league.services.accounts import create_player, ensure_user_for_player

    grp, players = _group()
    dup, _ = create_player(f"Dup {datetime.utcnow().timestamp()}", commit=False)
    keep = players[1]
    ensure_user_for_player(keep, commit=False)
    comp2 = f.competition(name=f"Other {datetime.utcnow().timestamp()}")
    f.entry(comp2, dup)
    dup_id = dup.id
    moved = subs.merge_players(dup_id, keep.id, dry_run=False)
    assert moved["entries.player_id"] == 1 and moved["users (deleted)"] == 1
    assert db.session.get(Player, dup_id) is None
    assert Entry.query.filter_by(competition_id=comp2.id, player_id=keep.id).count() == 1


def test_merge_players_refuses_two_people_of_the_same_competition(pg):
    _, players = _group()
    with pytest.raises(subs.ImportError_, match="share a competition"):
        subs.merge_players(players[0].id, players[1].id, dry_run=True)


def test_swap_roster_player_replaces_an_undrawn_entry(pg):
    from padel_league.services.accounts import create_player
    from padel_league.services.imports.roster import swap_roster_player

    comp = f.competition(name=f"Teams {datetime.utcnow().timestamp()}", format="teams")
    out_player = f.player()
    f.entry(comp, out_player)
    newcomer, _ = create_player(f"Novo {datetime.utcnow().timestamp()}", commit=False)
    db.session.execute(text("update players set status = 'external' where id = :i"), {"i": newcomer.id})
    done = swap_roster_player(comp.id, out_player.id, newcomer.id, dry_run=False)
    assert Entry.query.filter_by(competition_id=comp.id, player_id=out_player.id).first() is None
    assert Entry.query.filter_by(competition_id=comp.id, player_id=newcomer.id).one().status == "active"
    assert db.session.execute(text("select status from players where id = :i"), {"i": newcomer.id}).scalar() == "member"
    assert done["login_created"] is False and done["login"]


def test_swap_roster_player_refuses_a_drawn_entry(pg):
    from padel_league.services.imports.roster import RosterError, swap_roster_player

    grp, players = _group()
    with pytest.raises(RosterError, match="group_members"):
        swap_roster_player(grp.stage.competition_id, players[0].id, f.player().id, dry_run=True)


def test_sheet_error_decision_replaces_the_mismatch_flag(pg):
    grp, _, _, row, names = _setup("Sub Sheet Error")
    row["points"] = 3  # the DB side scored 0 (no results)
    subs.run([row], names, {1: {"action": "sheet_error", "value": "", "reason": "sheet error confirmed"}},
             dry_run=False)
    event = AuditEvent.query.filter_by(action="substitute_imported").order_by(AuditEvent.id.desc()).first()
    assert event.after["points_note"] == "sheet error confirmed" and "points_mismatch" not in event.after
