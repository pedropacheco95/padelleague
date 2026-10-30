"""Ranking points awarded by a finished group. Stored unrounded; only display rounds.

Clássica and Teams: place points int(rating * 0.75^(place-1)) plus an individual
bonus wins * rating/100 + draws * rating/250 (Teams counts sets, not matches;
players sharing a place share its place points but keep their own bonus).

Shuffle (decision 2026-10-15): one curve over the 48 overall places,
×0.85 per place from 1st to 8th (2000 → 641), then ×0.90 per place to 48th,
int() truncation, no bonus. Evaluated as one power product, not step by step:
2000·0.85² is 1444.999…, so place 3 is 1444 and the 48 places total 15,364.
"""

from dataclasses import dataclass

PLACE_DECAY = 0.75
WIN_BONUS_DIVISOR = 100
DRAW_BONUS_DIVISOR = 250

# Teams ratings already are a quarter of the Clássica ones: never divide again.
TEAMS_RATINGS = {1: 500, 2: 250, 3: 125, 4: 63, 5: 31, 6: 16}
# A Teams division: 4 pairs, 3 round-robin matches per pair (services.teams_divisions.ROUND_ROBIN)
# of 3 sets each (domain.standings.TEAMS_SETS_PER_MATCH); standings are per player, 8 rows.
TEAMS_MATCHES_PER_PAIR = 3
TEAMS_SETS_PER_MATCH = 3
TEAMS_PLAYERS_PER_DIVISION = 8

SHUFFLE_TOP = 2000
SHUFFLE_FIRST_RATIO = 0.85
SHUFFLE_REST_RATIO = 0.90
SHUFFLE_BREAK_PLACE = 8
SHUFFLE_PLACES = 48


@dataclass(frozen=True)
class AwardLine:
    entry_id: int
    player_id: int
    place: int
    rating: int | None
    place_points: float
    bonus_points: float
    wins: int
    draws: int

    @property
    def total(self):
        return self.place_points + self.bonus_points


def place_points(rating, place, decay=PLACE_DECAY):
    return float(int(rating * decay ** (place - 1)))


def bonus_points(rating, wins, draws, win_divisor=WIN_BONUS_DIVISOR, draw_divisor=DRAW_BONUS_DIVISOR):
    return wins * rating / win_divisor + draws * rating / draw_divisor


def teams_points_range(rating):
    """(min, max) ranking points one player can take out of a Teams division of `rating`.

    max: 1st place with every set of the pair's 3 matches won (9 set bonuses).
    min: 8th place with no set won or drawn. A pair that plays everything and
    loses everything shares 7th; 8th is one player's floor when the partner
    has more presences (an absence), since ties share the highest place.
    """
    best = place_points(rating, 1) + bonus_points(rating, TEAMS_MATCHES_PER_PAIR * TEAMS_SETS_PER_MATCH, 0)
    worst = place_points(rating, TEAMS_PLAYERS_PER_DIVISION)
    return worst, best


def group_awards(rows, rating):
    """Awards for a finished Clássica or Teams group from its standings rows.

    For Teams, rows carry sets in wins/draws (see domain.standings.teams_standings).
    """
    return [
        AwardLine(
            entry_id=r.entry_id,
            player_id=r.player_id,
            place=r.place,
            rating=rating,
            place_points=place_points(rating, r.place),
            bonus_points=bonus_points(rating, r.wins, r.draws),
            wins=r.wins,
            draws=r.draws,
        )
        for r in rows
    ]


def shuffle_place_points(place):
    if not 1 <= place <= SHUFFLE_PLACES:
        return 0.0
    first = min(place - 1, SHUFFLE_BREAK_PLACE - 1)
    rest = max(place - SHUFFLE_BREAK_PLACE, 0)
    return float(int(SHUFFLE_TOP * SHUFFLE_FIRST_RATIO**first * SHUFFLE_REST_RATIO**rest))


def shuffle_curve():
    return [shuffle_place_points(p) for p in range(1, SHUFFLE_PLACES + 1)]
