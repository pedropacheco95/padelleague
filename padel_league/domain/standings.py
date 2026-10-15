"""Group standings, computed from match facts. Pure: callers pass plain data.

Clássica (and Shuffle groups): one set per match, 3 points a win, 1 a draw;
order by points, then appearances (presenças), then games difference
(master c2540a7), then the member's order (seed / group member id), so
places are always distinct.

Teams: every match is up to 3 set results between two pairs; a won set is 3
points, a drawn set (time-out or never started) 1, a lost set 0. Points are
individual: a player scores the sets of the matches they actually played.
Absent players score nothing and lose the presence; substitutes are never
members and score nothing. Order by set points, then presences, and nothing
else: players tied on both share the highest place of the tie.
"""

from dataclasses import dataclass, field

from padel_league.domain.errors import InvalidInput

SET_OUTCOMES = ("completed", "timeout_draw", "not_started")
TEAMS_SETS_PER_MATCH = 3
CLASSICA_MATCHES_PER_ROUND = 3


@dataclass(frozen=True)
class Member:
    entry_id: int
    player_id: int
    order: int  # tie-break of last resort (seed, else group member id)


@dataclass(frozen=True)
class SetResult:
    home_games: int | None
    away_games: int | None
    outcome: str = "completed"


@dataclass(frozen=True)
class MatchFacts:
    """A played match. home/away: entry ids of the members who actually played."""

    round_number: int
    home: tuple
    away: tuple
    sets: tuple = ()
    walkover_winner: str | None = None  # 'home' | 'away'


@dataclass
class StandingRow:
    entry_id: int
    player_id: int
    place: int = 0
    points: float = 0
    appearances: int = 0
    attendance_pct: float | None = None
    wins: int = 0
    draws: int = 0
    losses: int = 0
    games_won: int = 0
    games_lost: int = 0
    sets_won: int | None = None
    sets_drawn: int | None = None
    sets_lost: int | None = None
    order: int = field(default=0, repr=False)

    @property
    def games_difference(self):
        return self.games_won - self.games_lost


def _sides(match):
    return (("home", match.home), ("away", match.away))


# --- Clássica ---------------------------------------------------------------------


def classica_standings(members, matches, rounds_played=None):
    """Standings of a one-set-per-match group.

    `matches` are the played matches. `rounds_played` is the number of rounds
    that have results (defaults to the highest played round number); it is the
    attendance denominator: each player is due 3 matches per round.
    """
    rows = {m.entry_id: StandingRow(m.entry_id, m.player_id, order=m.order) for m in members}
    for match in matches:
        if not match.sets:
            continue
        s = match.sets[0]
        if s.home_games is None or s.away_games is None:
            continue
        for side, entries in _sides(match):
            mine, theirs = (s.home_games, s.away_games) if side == "home" else (s.away_games, s.home_games)
            for entry_id in entries:
                row = rows.get(entry_id)
                if row is None:
                    continue
                row.appearances += 1
                row.games_won += mine
                row.games_lost += theirs
                if mine > theirs:
                    row.wins += 1
                elif mine == theirs:
                    row.draws += 1
                else:
                    row.losses += 1
    if rounds_played is None:
        rounds_played = max((m.round_number for m in matches), default=0)
    for row in rows.values():
        row.points = 3 * row.wins + row.draws
        row.attendance_pct = attendance_pct(row.appearances, rounds_played * CLASSICA_MATCHES_PER_ROUND)
    ordered = sorted(rows.values(), key=lambda r: (-r.points, -r.appearances, -r.games_difference, r.order))
    for place, row in enumerate(ordered, start=1):
        row.place = place
    return ordered


def attendance_pct(appearances, due):
    """Percentage 0-100 (fixes B3, which stored 100% as 787.5). None before any round."""
    return appearances / due * 100 if due else None


# --- Teams ---------------------------------------------------------------------------


def set_points(result):
    """(home_points, away_points) of one Teams set."""
    if result.outcome not in SET_OUTCOMES:
        raise InvalidInput(f"Resultado de set inválido: {result.outcome}.", "invalid_set_outcome")
    if result.outcome != "completed":
        return 1, 1
    if result.home_games is None or result.away_games is None or result.home_games == result.away_games:
        raise InvalidInput("Um set terminado precisa de jogos e de um vencedor.", "invalid_set_score")
    return (3, 0) if result.home_games > result.away_games else (0, 3)


def teams_match_points(match):
    """[(home_points, away_points)] per set; a walkover is three sets 3-0 to the present pair."""
    if match.walkover_winner is not None:
        if match.walkover_winner not in ("home", "away"):
            raise InvalidInput("Vencedor de falta de comparência inválido.", "invalid_walkover")
        won = (3, 0) if match.walkover_winner == "home" else (0, 3)
        return [won] * TEAMS_SETS_PER_MATCH
    if len(match.sets) != TEAMS_SETS_PER_MATCH:
        raise InvalidInput("Um encontro da Teams tem sempre exatamente 3 sets.", "teams_needs_three_sets")
    return [set_points(s) for s in match.sets]


def teams_standings(members, matches):
    rows = {
        m.entry_id: StandingRow(m.entry_id, m.player_id, order=m.order, sets_won=0, sets_drawn=0, sets_lost=0)
        for m in members
    }
    for match in matches:
        per_set = teams_match_points(match)
        for side, entries in _sides(match):
            if match.walkover_winner is not None and side != match.walkover_winner:
                # Walkover, losing side (Pedro, 2026-10-15): a player who turned up
                # keeps the presence and scores 0; the absent partner was marked
                # absent (no participant row) and loses it.
                for entry_id in entries:
                    if entry_id in rows:
                        rows[entry_id].appearances += 1
                continue
            for entry_id in entries:
                row = rows.get(entry_id)
                if row is None:
                    continue
                row.appearances += 1
                for home_pts, away_pts in per_set:
                    mine = home_pts if side == "home" else away_pts
                    row.points += mine
                    if mine == 3:
                        row.sets_won += 1
                    elif mine == 1:
                        row.sets_drawn += 1
                    else:
                        row.sets_lost += 1
                if match.walkover_winner is None:
                    for s in match.sets:
                        if s.home_games is not None and s.away_games is not None:
                            row.games_won += s.home_games if side == "home" else s.away_games
                            row.games_lost += s.away_games if side == "home" else s.home_games
    for row in rows.values():
        row.wins, row.draws, row.losses = row.sets_won, row.sets_drawn, row.sets_lost
    rounds = max((m.round_number for m in matches), default=0)
    for row in rows.values():
        row.attendance_pct = attendance_pct(row.appearances, rounds)
    ordered = sorted(rows.values(), key=lambda r: (-r.points, -r.appearances, r.order))
    return assign_shared_places(ordered, key=lambda r: (r.points, r.appearances))


def assign_shared_places(ordered, key):
    """Competition ranking ("1, 2, 3, 3, 5"): ties share the highest place of the tie."""
    previous = object()
    for index, row in enumerate(ordered, start=1):
        k = key(row)
        if k != previous:
            place, previous = index, k
        row.place = place
    return ordered
