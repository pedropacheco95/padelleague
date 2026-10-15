"""Group standings on the v2 model: frozen snapshot rows, or computed live.

A group whose standings were snapshotted (at close-out, or imported at
migration) returns exactly the stored rows. Otherwise the rows are computed
by padel_league.domain.standings from the played matches. Read-only.
"""

from dataclasses import dataclass

from padel_league.domain import standings as rules
from padel_league.domain.errors import NotFound
from padel_league.models.v2 import CompetitionGroup, CompetitionMatch, Entry, GroupMember, Round, StandingSnapshot
from padel_league.sql_db import db

COUNTED_STATUSES = ("played", "walkover")


@dataclass
class GroupStandings:
    group_id: int
    format: str
    frozen: bool
    rows: list  # [domain.standings.StandingRow]


def _group(group_id):
    group = db.session.get(CompetitionGroup, group_id)
    if group is None:
        raise NotFound(f"Grupo {group_id} não existe.", "group_not_found")
    return group


def group_members(group_id):
    rows = (
        db.session.query(GroupMember.id, GroupMember.entry_id, GroupMember.seed)
        .filter(GroupMember.group_id == group_id)
        .all()
    )
    players = dict(db.session.query(Entry.id, Entry.player_id).filter(Entry.id.in_([r.entry_id for r in rows])).all())
    return [rules.Member(entry_id=r.entry_id, player_id=players[r.entry_id], order=r.id) for r in rows]


def match_facts(group_id):
    """Played (or walked-over) matches of a group as domain facts; only members score."""
    matches = (
        CompetitionMatch.query.filter(
            CompetitionMatch.group_id == group_id, CompetitionMatch.status.in_(COUNTED_STATUSES)
        )
        .join(Round, Round.id == CompetitionMatch.round_id)
        .with_entities(CompetitionMatch, Round.number)
        .all()
    )
    facts = []
    for match, round_number in matches:
        sides = {"home": [], "away": []}
        for p in sorted(match.participants, key=lambda p: (p.side, p.slot)):
            if p.role == "member" and p.entry_id is not None:
                sides[p.side].append(p.entry_id)
        sets = tuple(rules.SetResult(s.home_games, s.away_games, s.outcome) for s in match.sets)
        walkover = getattr(match, "walkover_winner", None) if match.status == "walkover" else None
        facts.append(rules.MatchFacts(round_number, tuple(sides["home"]), tuple(sides["away"]), sets, walkover))
    return facts


def compute_rows(group):
    members = group_members(group.id)
    facts = match_facts(group.id)
    if group.stage.competition.format == "teams":
        return rules.teams_standings(members, facts)
    return rules.classica_standings(members, facts)


def rounds_played(group_id):
    return (
        db.session.query(db.func.max(Round.number))
        .join(CompetitionMatch, CompetitionMatch.round_id == Round.id)
        .filter(CompetitionMatch.group_id == group_id, CompetitionMatch.status.in_(COUNTED_STATUSES))
        .scalar()
        or 0
    )


def _snapshot_attendance(s, rounds):
    """Rows imported at migration store the B3 value (100% as 787.5) over a
    sometimes stale matchweek: recompute it over the rounds actually played."""
    if s.source == "legacy":
        return rules.attendance_pct(s.appearances or 0, rounds * rules.CLASSICA_MATCHES_PER_ROUND)
    return s.percentage_of_appearances


def _snapshot_rows(group_id):
    rows = (
        db.session.query(StandingSnapshot, GroupMember.id)
        .join(GroupMember, GroupMember.id == StandingSnapshot.group_member_id)
        .filter(GroupMember.group_id == group_id)
        .all()
    )
    players = dict(
        db.session.query(Entry.id, Entry.player_id).filter(Entry.id.in_([s.entry_id for s, _ in rows])).all()
    )
    rounds = rounds_played(group_id) if rows else 0
    out = [
        rules.StandingRow(
            entry_id=s.entry_id,
            player_id=players[s.entry_id],
            place=s.place,
            points=s.points,
            appearances=s.appearances,
            attendance_pct=_snapshot_attendance(s, rounds),
            wins=s.wins,
            draws=s.draws,
            losses=s.losses,
            games_won=s.games_won,
            games_lost=s.games_lost,
            order=gm_id,
        )
        for s, gm_id in rows
    ]
    return sorted(out, key=lambda r: (r.place if r.place is not None else 10**9, r.order))


def group_standings(group_id):
    group = _group(group_id)
    fmt = group.stage.competition.format
    member_count = GroupMember.query.filter_by(group_id=group_id).count()
    frozen = _snapshot_rows(group_id)
    if frozen and len(frozen) == member_count:
        return GroupStandings(group_id, fmt, True, frozen)
    return GroupStandings(group_id, fmt, False, compute_rows(group))
