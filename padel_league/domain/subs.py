"""Substitute points (Pedro, 2026-10-16; regulation art. 12).

A substitute scores, per match they played, the points the standings give
that side for the format (Clássica and Shuffle 3/1/0 on the one set, Teams the
sum of the set points), times the multiplier of the division they subbed in:
the Clássica/Teams division tier by SUBS_MULTIPLIERS, the Shuffle group its own
multiplier. Which competitions count is the ranking rule's `subs_window`
(services.ranking): the last completed one, or the ranking window.
"""

from dataclasses import dataclass

from padel_league.domain.standings import MatchFacts, teams_match_points

# Division tier -> multiplier (the SUBS_ sheet's `mult` column).
SUBS_MULTIPLIERS = {1: 10, 2: 8, 3: 6, 4: 5, 5: 4, 6: 3}


@dataclass(frozen=True)
class SubMatch:
    """One match a substitute played: which side, in which group (of which format)."""

    player_id: int
    group_id: int
    side: str  # 'home' | 'away'
    match: MatchFacts
    fmt: str = "classica"


def group_multiplier(fmt, tier, own_multiplier=None):
    """The multiplier of a group, or None when the tier has none (no subs points)."""
    if fmt == "shuffle":
        return own_multiplier or 1
    return SUBS_MULTIPLIERS.get(tier)


def side_points(fmt, match, side):
    """The points the standings give one side of a played match."""
    if fmt == "teams":
        return sum(home if side == "home" else away for home, away in teams_match_points(match))
    if match.walkover_winner is not None:
        return 3 if match.walkover_winner == side else 0
    if not match.sets:
        return 0
    s = match.sets[0]
    if s.home_games is None or s.away_games is None:
        return 0
    mine, theirs = (s.home_games, s.away_games) if side == "home" else (s.away_games, s.home_games)
    return 3 if mine > theirs else 1 if mine == theirs else 0


@dataclass
class SubsLine:
    player_id: int
    points: float = 0.0
    matches: int = 0
    by_group: dict = None  # group_id -> (raw points, multiplier, matches)
    position: int = 0


def subs_points(sub_matches, multipliers):
    """[SubsLine] by points desc (then player id), distinct positions.

    `multipliers` is {group_id: multiplier or None}; groups without one score 0.
    """
    lines = {}
    for sm in sub_matches:
        mult = multipliers.get(sm.group_id)
        line = lines.setdefault(sm.player_id, SubsLine(sm.player_id, by_group={}))
        raw, _, n = line.by_group.get(sm.group_id, (0, mult, 0))
        pts = side_points(sm.fmt, sm.match, sm.side)
        line.by_group[sm.group_id] = (raw + pts, mult, n + 1)
        line.matches += 1
        line.points += pts * (mult or 0)
    ordered = sorted(lines.values(), key=lambda l: (-l.points, l.player_id))
    for position, line in enumerate(ordered, start=1):
        line.position = position
    return ordered
