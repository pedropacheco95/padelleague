"""Import who substituted whom (Pedro's SUBS_ sheet, editions 18ª–22ª) into v2.

Before v2 an absent player's `players_in_match` rows were deleted, so history
only shows an empty slot ("Substituto"). The sheet names the substitute. This
fills those slots with `match_participants` rows of role 'substitute' — no
entry, so standings, points and awards do not move (both the v2 standings and
the compat views count members by entry) — and records the link to the
derived absence as an audit event, since absences have no participant column.

Inputs, all reviewed by Pedro before a run:
  * the sheet rows as JSON (edition, sub, replaced, jornada, division, partner, points)
  * docs/v2/subs_name_map.csv  — sheet name -> player id | NEW | UNKNOWN_SUB | …
  * docs/v2/subs_row_decisions.csv — per-row skip / override / note

Duplicate players are merged first, separately, with `merge_players`.
"""

import collections
import csv
import json
import secrets
from dataclasses import dataclass, field

from sqlalchemy import text
from werkzeug.security import generate_password_hash

from padel_league.models import Player, User
from padel_league.models.v2 import (
    Absence,
    AuditEvent,
    Competition,
    CompetitionGroup,
    CompetitionMatch,
    Entry,
    GroupMember,
    MatchParticipant,
    Round,
    Stage,
)
from padel_league.services import accounts
from padel_league.sql_db import db

# Sheet edition number -> competition id (18ª, 19ª, 20ª Shuffle, 21ª, 22ª).
EDITION_COMPETITION = {18: 22, 19: 23, 20: 26, 21: 24, 22: 25}
SHUFFLE_COMPETITIONS = {26}
NO_PERSON = {"UNKNOWN_SUB", "PLACEHOLDER"}


class ImportError_(Exception):
    """The inputs are inconsistent; nothing is written."""


# --- inputs


def load_name_map(path):
    """{sheet name: {"resolution", "ids"}} from subs_name_map.csv."""
    out = {}
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            out[r["name"]] = {"resolution": r["resolution"], "ids": r["player_ids"].strip()}
    return out


def load_decisions(path):
    """{sheet row: {"action", "value", "reason"}} from subs_row_decisions.csv."""
    if not path:
        return {}
    with open(path, newline="") as fh:
        return {int(r["row"]): r for r in csv.DictReader(fh)}


def _person(name_map, name, role):
    """('player', id) | ('new', canonical name) | ('none', why) | ('unresolved', why)."""
    name = (name or "").strip()
    entry = name_map.get(name)
    if entry is None:
        return "unresolved", f"{name!r} is not in the name map"
    res, ids = entry["resolution"], entry["ids"]
    if res == "PLAYER":
        return "player", int(ids)
    if res == "BY_ROLE":
        by_role = dict(part.strip().split("=") for part in ids.split(";"))
        key = "sub" if role == "sub" else "replaced"
        if key not in by_role:
            return "unresolved", f"{name!r} has no id for role {role}"
        return "player", int(by_role[key])
    if res == "NEW":
        return "new", ids[1:].strip() if ids.startswith("=") else name
    if res in NO_PERSON:
        return "none", f"{name!r} is {res}"
    return "unresolved", f"{name!r} is {res}"


# --- the round's empty seats


def _round_ids(competition_id, jornada, division):
    """(group_id, round_id) for a sheet row, or (None, None)."""
    if competition_id in SHUFFLE_COMPETITIONS:
        # Shuffle: one stage per jornada, its groups are that jornada's divisions.
        stage = Stage.query.filter_by(competition_id=competition_id, number=jornada).first()
        rnd = Round.query.filter_by(stage_id=stage.id).first() if stage else None
    else:
        stage = Stage.query.filter_by(competition_id=competition_id, number=1).first()
        rnd = Round.query.filter_by(stage_id=stage.id, number=jornada).first() if stage else None
    group = CompetitionGroup.query.filter_by(stage_id=stage.id, tier=division).first() if stage else None
    return (group.id if group else None), (rnd.id if rnd else None)


def _result_points(match, side):
    sets = sorted(match.sets, key=lambda s: s.set_no)
    if not sets:
        return 0
    mine, theirs = (sets[0].home_games, sets[0].away_games) if side == "home" else (sets[0].away_games, sets[0].home_games)
    return 3 if mine > theirs else 1 if mine == theirs else 0


@dataclass
class _Pair:
    """One side's empty seats across the jornada: pairs are fixed within a jornada."""

    present: frozenset
    seats: list = field(default_factory=list)  # [(match, side, free slots)]
    points: int = 0

    def capacity(self):
        return min(len(free) for _, _, free in self.seats)


def _empty_pairs(group_id, round_id):
    pairs = {}
    matches = CompetitionMatch.query.filter_by(group_id=group_id, round_id=round_id).order_by(CompetitionMatch.id)
    for match in matches:
        for side in ("home", "away"):
            here = [p for p in match.participants if p.side == side]
            free = sorted({1, 2} - {p.slot for p in here})
            if not free:
                continue
            key = frozenset(p.player_id for p in here)
            pair = pairs.setdefault(key, _Pair(present=key))
            pair.seats.append((match, side, free))
            pair.points += _result_points(match, side)
    return pairs


# --- planning


@dataclass
class Planned:
    row: int
    sheet: dict
    action: str  # "seat" | "note"
    sub: tuple
    group_id: int = None
    round_id: int = None
    entry: Entry = None
    absence: Absence = None
    pair: _Pair = None
    two_subs: bool = False
    points_note: str = None  # decision "sheet_error": the DB result stands, the sheet's points were wrong
    db_points: int = None


def plan(rows, name_map, decisions):
    """Decide every row without writing. Returns (planned, skipped [(row, reason)])."""
    planned, skipped = [], []
    by_round = collections.defaultdict(list)
    for i, r in enumerate(rows, start=1):
        d = decisions.get(i, {})
        action = d.get("action", "")
        if action == "skip":
            skipped.append((i, f"decision: {d['reason']}"))
            continue
        comp = r.get("competition_id") or EDITION_COMPETITION.get(r.get("edition"))
        division = int(d["value"]) if action == "division" else r["division"]
        group_id, round_id = _round_ids(comp, r["jornada"], division) if comp else (None, None)
        if group_id is None or round_id is None:
            skipped.append((i, "no v2 group/round for this edition, division and jornada"))
            continue
        if action == "replaced":
            replaced = ("player", int(d["value"]))
        else:
            replaced = _person(name_map, r["replaced"], "replaced")
        if replaced[0] != "player":
            skipped.append((i, f"replaced player: {replaced[1]}"))
            continue
        entry = Entry.query.filter_by(competition_id=comp, player_id=replaced[1]).first()
        if entry is None:
            skipped.append((i, f"replaced player {replaced[1]} has no entry in competition {comp}"))
            continue
        sub = _person(name_map, r["sub"], "sub")
        if sub[0] == "none":
            skipped.append((i, f"unknown substitute, the slot stays empty ({sub[1]})"))
            continue
        if sub[0] == "unresolved":
            skipped.append((i, f"substitute: {sub[1]}"))
            continue
        item = Planned(row=i, sheet=r, action="note" if action == "note" else "seat", sub=sub,
                       group_id=group_id, round_id=round_id, entry=entry)
        if action == "sheet_error":
            item.points_note = d["reason"]
        if item.action == "note":
            planned.append(item)
            continue
        item.absence = Absence.query.filter_by(entry_id=entry.id, round_id=round_id).first()
        if item.absence is None:
            skipped.append((i, f"replaced player {replaced[1]} has no absence in that jornada"))
            continue
        by_round[(group_id, round_id)].append(item)

    for (group_id, round_id), items in by_round.items():
        pairs = _empty_pairs(group_id, round_id)
        left = {k: p.capacity() for k, p in pairs.items()}
        members = {
            pid for (pid,) in db.session.query(Entry.player_id).join(GroupMember, GroupMember.entry_id == Entry.id)
            .filter(GroupMember.group_id == group_id)
        }
        sub_names = {it.sheet["sub"].strip() for it in items}
        sub_ids = {it.sub[1] for it in items if it.sub[0] == "player"}
        # Rows whose partner is a member left on a side: that side, unambiguously.
        rest = []
        for it in items:
            partner = _person(name_map, it.sheet["partner"], "partner")
            if partner[0] == "player" and partner[1] in members:
                key = frozenset([partner[1]])
                if key in pairs and left[key] > 0:
                    it.pair, left[key] = pairs[key], left[key] - 1
                else:
                    skipped.append((it.row, f"partner {partner[1]} has no empty seat beside them that jornada"))
                continue
            it.two_subs = it.sheet["partner"].strip() in sub_names or (partner[0] == "player" and partner[1] in sub_ids)
            rest.append(it)
        # Partner is another substitute, a non-member or unknown: the remaining side with the sheet's points.
        for it in rest:
            fits = [k for k, n in left.items() if n > 0 and pairs[k].points == it.sheet["points"]
                    and (not it.two_subs or not k)]
            if len(fits) == 1:
                it.pair, left[fits[0]] = pairs[fits[0]], left[fits[0]] - 1
            else:
                skipped.append((it.row, f"cannot place the seat: {len(fits)} empty sides fit "
                                        f"(points {it.sheet['points']})"))
        for it in items:
            if it.pair is not None:
                it.db_points = it.pair.points
                planned.append(it)
    planned.sort(key=lambda it: it.row)
    return planned, skipped


# --- writing


def _set_external(player_id):
    db.session.execute(text("update players set status = 'external' where id = :id"), {"id": player_id})


def lock_password(user):
    """Replace the onboarding password (= username, guessable) with an unusable random one.

    The token is never printed or stored; access comes later from an admin
    setting a password or from forgot-password.
    """
    user.password = generate_password_hash(secrets.token_urlsafe(32))
    db.session.flush()


def _new_player(name, created):
    if name in created:
        return created[name]
    if Player.query.filter((Player.name == name) | (Player.full_name == name)).first():
        raise ImportError_(f"a player named {name!r} already exists; map the name to it instead of NEW")
    player, user = accounts.create_player(name, name=name, commit=False)
    lock_password(user)
    _set_external(player.id)
    created[name] = player.id
    return player.id


def run(rows, name_map, decisions, actor_user_id=None, dry_run=True):
    """Plan and write in one transaction; roll back when dry_run. Returns a report dict."""
    planned, skipped = plan(rows, name_map, decisions)
    groups = sorted({it.group_id for it in planned})
    before = _tables(groups)
    created, written, notes, imported, mismatches = {}, 0, 0, 0, []
    try:
        for it in planned:
            sub_id = it.sub[1] if it.sub[0] == "player" else _new_player(it.sub[1], created)
            if it.action == "note":
                db.session.add(AuditEvent(
                    actor_user_id=actor_user_id, entity="entry", entity_id=it.entry.id,
                    action="substitute_note",
                    after={"round_id": it.round_id, "played_by_player_id": sub_id, "sheet_row": it.row,
                           "note": "the substitute played in this seat; results stay with the member"},
                ))
                notes += 1
                continue
            clash = [m.id for m, _, _ in it.pair.seats if any(p.player_id == sub_id for p in m.participants)]
            if clash:
                skipped.append((it.row, f"substitute {sub_id} already plays in match(es) {clash} of that jornada"))
                continue
            participant_ids = []
            for match, side, free in it.pair.seats:
                slot = free.pop(0)
                mp = MatchParticipant(match_id=match.id, side=side, slot=slot, role="substitute", player_id=sub_id)
                db.session.add(mp)
                match.participants.append(mp)
                db.session.flush()
                participant_ids.append(mp.id)
            db.session.add(AuditEvent(
                actor_user_id=actor_user_id, entity="absence", entity_id=it.absence.id,
                action="substitute_imported",
                after={"sheet_row": it.row, "substitute_player_id": sub_id, "match_participant_ids": participant_ids,
                       "sheet_points": it.sheet["points"], "db_points": it.db_points,
                       **({"points_note": it.points_note} if it.points_note
                          else {"points_mismatch": it.db_points != it.sheet["points"]})},
            ))
            written += len(participant_ids)
            imported += 1
            if it.db_points != it.sheet["points"] and not it.points_note:
                mismatches.append(it.row)
        db.session.flush()
        db.session.expire_all()
        after = _tables(groups)
        changed = [g for g in before if before[g] != after[g]]
        if changed:
            raise ImportError_(f"standings changed in groups {changed}; nothing written")
        report = {
            "rows": len(rows),
            "rows_imported": imported,
            "rows_noted": notes,
            "participants_written": written,
            "players_created": sorted(created),
            "rows_skipped": skipped,
            "points_mismatch_rows": mismatches,
            "groups_checked_unchanged": len(groups),
            "competitions_checked_unchanged": len(before) - len(groups),
            "dry_run": dry_run,
        }
        if dry_run:
            db.session.rollback()
        else:
            db.session.commit()
        return report
    except Exception:
        db.session.rollback()
        raise


def _tables(group_ids):
    """Everything a substitute must not move: live v2 rows, published rows, and the v1 view."""
    from dataclasses import asdict

    from padel_league.services.standings import competition_standings, compute_rows, group_standings

    out = {}
    for gid in group_ids:
        group = db.session.get(CompetitionGroup, gid)
        out[gid] = (
            [asdict(r) for r in compute_rows(group)],
            [asdict(r) for r in group_standings(gid).rows],
            [tuple(r) for r in db.session.execute(
                text("select * from compat.players_in_division where division_id = :g order by id"), {"g": gid})],
        )
    comps = {cid for (cid,) in db.session.query(Stage.competition_id).join(CompetitionGroup, CompetitionGroup.stage_id == Stage.id)
             .filter(CompetitionGroup.id.in_(group_ids))}
    for cid in sorted(comps):
        if Competition.query.get(cid).format == "classica":
            continue  # no competition table; its groups are checked above
        out[f"competition {cid}"] = (
            [asdict(r) for r in competition_standings(cid).rows],
            [tuple(r) for r in db.session.execute(
                text("select t.* from compat.players_in_shuffle_tournament t join compat.shuffle_tournaments s "
                     "on s.id = t.shuffle_tournament_id where s.competition_id = :c order by t.id"),
                {"c": cid})],
        )
    return out


# --- merging duplicate players

_REPOINT = [
    ("entries", "player_id"),
    ("match_participants", "player_id"),
    ("awards", "player_id"),
    ("golden_tickets", "player_id"),
    ("registrations", "player_id"),
    ("teams_players", "player_id"),
    ("teams_pairs", "player_a_id"),
    ("teams_pairs", "player_b_id"),
    ("teams_partner_requests", "player_id"),
    ("teams_partner_requests", "partner_id"),
]
# Published ranking history: one row per player per snapshot, so the duplicate's
# rows are dropped (recompute the ranking afterwards to merge their points).
_DROP = [("ranking_entries", "player_id"), ("ranking_slot_values", "player_id")]


def merge_players(from_id, into_id, actor_user_id=None, dry_run=True):
    """Repoint everything of `from_id` to `into_id`, then delete `from_id` and its login.

    Refuses when both played the same competition or the same match (they would
    not be one person). Returns {table.column: rows} of what moved.
    """
    if from_id == into_id:
        raise ImportError_("from and into are the same player")
    src, dst = db.session.get(Player, from_id), db.session.get(Player, into_id)
    if src is None or dst is None:
        raise ImportError_("unknown player id")
    q = lambda sql, **kw: db.session.execute(text(sql), {"a": from_id, "b": into_id, **kw})  # noqa: E731
    clash = q("select count(*) from entries x join entries y on x.competition_id = y.competition_id "
              "where x.player_id = :a and y.player_id = :b").scalar()
    clash += q("select count(*) from match_participants x join match_participants y on x.match_id = y.match_id "
               "where x.player_id = :a and y.player_id = :b").scalar()
    if clash:
        raise ImportError_(f"players {from_id} and {into_id} share a competition or a match; not merging")
    moved = {}
    try:
        for table, col in _REPOINT:
            moved[f"{table}.{col}"] = q(f"update {table} set {col} = :b where {col} = :a").rowcount
        for table, col in _DROP:
            moved[f"{table}.{col} (dropped)"] = q(f"delete from {table} where {col} = :a").rowcount
        src_user = User.query.filter_by(player_id=from_id).first()
        dst_user = User.query.filter_by(player_id=into_id).first()
        if src_user is not None:
            if dst_user is None:
                src_user.player_id = into_id
                moved["users (repointed)"] = 1
            else:
                moved["orders.user_id"] = q("update orders set user_id = :u where user_id = :s",
                                            u=dst_user.id, s=src_user.id).rowcount
                db.session.delete(src_user)
                moved["users (deleted)"] = 1
        db.session.flush()
        before = {"player": {"id": src.id, "name": src.name, "full_name": src.full_name},
                  "user": src_user.username if src_user else None}
        db.session.delete(src)
        db.session.add(AuditEvent(actor_user_id=actor_user_id, entity="player", entity_id=into_id,
                                  action="merged_duplicate", before=before, after={"moved": moved}))
        db.session.flush()
        if dry_run:
            db.session.rollback()
        else:
            db.session.commit()
        return moved
    except Exception:
        db.session.rollback()
        raise


def load_rows(path):
    with open(path) as fh:
        return json.load(fh)
