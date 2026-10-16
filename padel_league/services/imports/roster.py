"""Swap one player of a not-yet-started roster for another (e.g. Teams 2026/27: João Mendonça for 91).

Only before the player is drawn into anything: refuses when the outgoing entry is
already in a group, a pair, a match, a vacancy or an award. Removes the outgoing
player's partner requests (v2 and the legacy teams_* tables), deletes their
entry, and gives the incoming player an entry, a login and member status.
"""

from sqlalchemy import text

from padel_league.models import Player
from padel_league.models.v2 import AuditEvent, Entry
from padel_league.services import accounts
from padel_league.sql_db import db


class RosterError(Exception):
    """The swap would touch history; nothing is written."""


_BLOCKING = [
    ("group_members", "entry_id = :e"),
    ("pairs", "entry_a_id = :e or entry_b_id = :e"),
    ("match_participants", "entry_id = :e"),
    ("absences", "entry_id = :e"),
    ("awards", "entry_id = :e"),
    ("standing_snapshots", "entry_id = :e"),
    ("vacancies", "opened_by_entry_id = :e or filled_entry_id = :e"),
]


def swap_roster_player(competition_id, out_player_id, in_player_id, actor_user_id=None, dry_run=True):
    q = lambda sql, **kw: db.session.execute(text(sql), kw)  # noqa: E731
    out_entry = Entry.query.filter_by(competition_id=competition_id, player_id=out_player_id).first()
    if out_entry is None:
        raise RosterError(f"player {out_player_id} has no entry in competition {competition_id}")
    incoming = db.session.get(Player, in_player_id)
    if incoming is None:
        raise RosterError(f"unknown player {in_player_id}")
    if Entry.query.filter_by(competition_id=competition_id, player_id=in_player_id).first():
        raise RosterError(f"player {in_player_id} already has an entry in competition {competition_id}")
    for table, where in _BLOCKING:
        n = q(f"select count(*) from {table} where {where}", e=out_entry.id).scalar()
        if n:
            raise RosterError(f"entry {out_entry.id} is already used in {table} ({n}); swap it by hand")
    done = {}
    try:
        done["partner_requests"] = q("delete from partner_requests where from_entry_id = :e or to_entry_id = :e",
                                     e=out_entry.id).rowcount
        done["teams_partner_requests"] = q("delete from teams_partner_requests where player_id = :p or partner_id = :p",
                                           p=out_player_id).rowcount
        done["teams_players (out)"] = q("delete from teams_players where player_id = :p", p=out_player_id).rowcount
        old = {"entry_id": out_entry.id, "player_id": out_player_id, "kind": out_entry.kind, "status": out_entry.status}
        db.session.delete(out_entry)
        db.session.flush()
        entry = Entry(competition_id=competition_id, player_id=in_player_id, kind=old["kind"], status="active")
        db.session.add(entry)
        q("insert into teams_players (player_id) values (:p) on conflict do nothing", p=in_player_id)
        q("update players set status = 'member' where id = :p", p=in_player_id)
        user, created = accounts.ensure_user_for_player(incoming, commit=False)
        if created:  # a new login must not keep the guessable username-as-password
            from padel_league.services.imports.substitutes import lock_password

            lock_password(user)
        db.session.flush()
        done.update({"entry_in": entry.id, "login": user.username, "login_created": created})
        db.session.add(AuditEvent(actor_user_id=actor_user_id, entity="competition", entity_id=competition_id,
                                  action="roster_swap", before=old,
                                  after={"entry_id": entry.id, "player_id": in_player_id, **done}))
        db.session.flush()
        if dry_run:
            db.session.rollback()
        else:
            db.session.commit()
        return done
    except Exception:
        db.session.rollback()
        raise
