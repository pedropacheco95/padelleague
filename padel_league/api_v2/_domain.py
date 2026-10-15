"""The one place /api/v2 touches S1's domain services (padel_league/services/standings.py,
ranking.py, closeout.py, results.record_sets). Until each lands, a read-only fallback
answers from stored rows, so swapping to S1 changes only this file.
"""

from dataclasses import dataclass, field
from typing import Optional

from padel_league.models.v2 import Entry, GroupMember, StandingSnapshot


@dataclass
class Row:
    entry_id: int
    player_id: int
    place: Optional[int]
    points: float = 0.0
    appearances: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    games_won: Optional[int] = None
    games_lost: Optional[int] = None
    sets_won: Optional[int] = None
    sets_drawn: Optional[int] = None
    attendance_pct: Optional[float] = None  # 0–100
    next_group_tier: Optional[int] = None


@dataclass
class Standings:
    frozen: bool
    rows: list = field(default_factory=list)


def _service(module, name):
    try:
        mod = __import__(f"padel_league.services.{module}", fromlist=[name])
    except ImportError:
        return None
    return getattr(mod, name, None)


def _from_s1(result):
    rows = [
        Row(
            entry_id=r.entry_id,
            player_id=r.player_id,
            place=r.place,
            points=r.points,
            appearances=r.appearances,
            wins=r.wins,
            draws=r.draws,
            losses=r.losses,
            games_won=getattr(r, "games_won", None),
            games_lost=getattr(r, "games_lost", None),
            sets_won=getattr(r, "sets_won", None),
            sets_drawn=getattr(r, "sets_drawn", None),
            attendance_pct=getattr(r, "attendance_pct", None),
        )
        for r in result.rows
    ]
    return Standings(frozen=result.frozen, rows=rows)


def _fallback(group_id):
    """Frozen snapshot rows when stored; otherwise members at zero, ordered by seed."""
    snaps = (
        StandingSnapshot.query.join(GroupMember, GroupMember.id == StandingSnapshot.group_member_id)
        .filter(GroupMember.group_id == group_id)
        .all()
    )
    if snaps:
        player_of = {e.id: e.player_id for e in Entry.query.filter(Entry.id.in_([s.entry_id for s in snaps]))}
        rows = [
            Row(
                entry_id=s.entry_id,
                player_id=player_of[s.entry_id],
                place=s.place,
                points=s.points or 0.0,
                appearances=s.appearances or 0,
                wins=s.wins or 0,
                draws=s.draws or 0,
                losses=s.losses or 0,
                games_won=s.games_won,
                games_lost=s.games_lost,
                attendance_pct=s.percentage_of_appearances,
            )
            for s in snaps
        ]
        return Standings(frozen=True, rows=sorted(rows, key=lambda r: (r.place is None, r.place or 0)))
    members = (
        GroupMember.query.filter_by(group_id=group_id)
        .join(Entry, Entry.id == GroupMember.entry_id)
        .with_entities(GroupMember.seed, Entry.id, Entry.player_id)
        .order_by(GroupMember.seed.nullslast(), Entry.id)
        .all()
    )
    return Standings(frozen=False, rows=[Row(entry_id=e, player_id=p, place=i) for i, (_, e, p) in enumerate(members, 1)])


def group_standings(group_id):
    service = _service("standings", "group_standings")
    if service is not None:
        return _from_s1(service(group_id))
    return _fallback(group_id)
