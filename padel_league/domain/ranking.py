"""The ranking: which awards count under a rule, totals, positions and the "why".

Rules (ranking_rules.mode):
- last_n_by_id: the n competitions with the highest ids (the pre-2026 rule:
  4 most recent editions by id, finished or not).
- last_n_completed_plus_current: the n most recently ended competitions (by
  end date) plus the current ones: not ended and starting after the last of
  those ended (2026/27: n = 3, current = Teams, each closed mini-tournament
  adding its awards).
- per_slot: per event slot, the latest competition of that slot that has
  awards; each new instance replaces its counterpart (2027/28+).

Which competitions are eligible at all is data, in ranking_rules.options:
  formats                   formats that count (default: all)
  exclude_competition_ids   never count these
  include_competition_ids   always eligible regardless of format
No rounding anywhere: totals are sums of unrounded awards.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from padel_league.domain.errors import InvalidInput

MODES = ("last_n_by_id", "last_n_completed_plus_current", "per_slot")


@dataclass(frozen=True)
class Rule:
    mode: str
    last_n: int | None = None
    options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CompetitionFact:
    id: int
    format: str
    status: str
    ends_on: date | None = None
    starts_on: date | None = None
    event_slot_id: int | None = None


@dataclass(frozen=True)
class AwardFact:
    player_id: int
    competition_id: int
    place_points: float
    bonus_points: float
    place: int | None = None
    group_id: int | None = None
    stage_number: int | None = None

    @property
    def total(self):
        return self.place_points + self.bonus_points


@dataclass(frozen=True)
class ExplainLine:
    competition_id: int
    stage_number: int | None
    group_id: int | None
    place: int | None
    place_points: float
    bonus_points: float
    counted: bool
    reason: str


@dataclass
class RankingLine:
    player_id: int
    points: float
    position: int = 0


@dataclass
class Ranking:
    counted_competition_ids: list
    lines: list
    explain: dict  # player_id -> [ExplainLine]

    def points_of(self, player_id):
        return next((l.points for l in self.lines if l.player_id == player_id), 0.0)


def _eligible(rule, competitions):
    opts = rule.options or {}
    formats = opts.get("formats")
    excluded = set(opts.get("exclude_competition_ids", ()))
    included = set(opts.get("include_competition_ids", ()))
    return [
        c
        for c in competitions
        if c.id not in excluded and (c.id in included or formats is None or c.format in formats)
    ]


def _date_key(c):
    return (c.ends_on or c.starts_on or date.min, c.id)


def counted_competitions(rule, competitions, awards=()):
    """{competition_id: reason it counts} under `rule`."""
    if rule.mode not in MODES:
        raise InvalidInput(f"Regra de ranking desconhecida: {rule.mode}.", "unknown_ranking_rule")
    eligible = _eligible(rule, competitions)
    if rule.mode == "last_n_by_id":
        chosen = sorted(eligible, key=lambda c: c.id, reverse=True)[: rule.last_n]
        return {c.id: f"uma das {rule.last_n} competições mais recentes" for c in chosen}
    if rule.mode == "last_n_completed_plus_current":
        ended = sorted((c for c in eligible if c.status == "ended"), key=_date_key, reverse=True)
        window = ended[: rule.last_n]
        out = {c.id: f"uma das {rule.last_n} últimas competições terminadas" for c in window}
        # Current: not ended and starting after the last completed one ended
        # (so a stale planned row from an old season never counts).
        since = max((c.ends_on for c in window if c.ends_on), default=date.min)
        out.update(
            {c.id: "competição em curso" for c in eligible if c.status != "ended" and (c.starts_on or date.max) >= since}
        )
        return out
    with_awards = {a.competition_id for a in awards}
    latest = {}
    for c in eligible:
        if c.event_slot_id is None or c.id not in with_awards:
            continue
        if c.event_slot_id not in latest or _date_key(c) > _date_key(latest[c.event_slot_id]):
            latest[c.event_slot_id] = c
    return {c.id: "edição mais recente deste evento" for c in latest.values()}


def compute(rule, competitions, awards, previous_positions=None):
    """Totals and positions from awards. Positions are distinct: points desc,
    then the previous position (as the old code did), then player id."""
    counted = counted_competitions(rule, competitions, awards)
    previous_positions = previous_positions or {}
    totals = defaultdict(float)
    explain = defaultdict(list)
    for a in sorted(awards, key=lambda a: (a.competition_id, a.stage_number or 0, a.group_id or 0)):
        counts = a.competition_id in counted
        if counts:
            totals[a.player_id] += a.total
        explain[a.player_id].append(
            ExplainLine(
                competition_id=a.competition_id,
                stage_number=a.stage_number,
                group_id=a.group_id,
                place=a.place,
                place_points=a.place_points,
                bonus_points=a.bonus_points,
                counted=counts,
                reason=counted[a.competition_id] if counts else "fora da janela do ranking",
            )
        )
    lines = [RankingLine(pid, pts) for pid, pts in totals.items()]
    lines.sort(key=lambda l: (-l.points, previous_positions.get(l.player_id) or 10**9, l.player_id))
    for position, line in enumerate(lines, start=1):
        line.position = position
    return Ranking(sorted(counted), lines, dict(explain))
