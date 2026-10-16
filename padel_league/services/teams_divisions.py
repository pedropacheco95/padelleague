"""PPL Teams divisions for one mini-tournament (stage), built from its closed pairs.

- Sum the ranking points of the two players of each pair; order the pairs by
  that sum; tie: the pair with the individually better-ranked player first.
- Slice into groups of 4 pairs: 1–4 → 1.ª divisão, 5–8 → 2.ª, …; ratings
  500/250/125/63/31/16. No promotion: rebuilt from scratch every stage.
- Each group plays a 3-round round robin between its 4 pairs, one match per
  pair per round: (1–2, 3–4), (1–3, 2–4), (1–4, 2–3).

The ranking is a parameter: by default the live ranking under the season rule
(2026/27: last 3 completed + current, so earlier mini-tournaments count).

project() is the partner simulator: the divisions close() + build_divisions()
would produce right now, optionally with one more pair, without writing.
"""

from dataclasses import dataclass, field
from datetime import datetime

from padel_league.domain.awards import TEAMS_RATINGS
from padel_league.domain.errors import Conflict
from padel_league.models.v2 import CompetitionGroup, CompetitionMatch, Entry, GroupMember, MatchParticipant, Round
from padel_league.services import ranking as ranking_svc
from padel_league.services import teams_pairing
from padel_league.sql_db import db

PAIRS_PER_DIVISION = 4
ROUND_ROBIN = [((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2))]
UNRANKED = 10**9


@dataclass(frozen=True)
class SeededPair:
    pair_id: int
    players: tuple
    points: float
    best_position: int


def seed_pairs(pairs, points, positions):
    """pairs: [(pair_id, (player_a, player_b))]; best first."""
    seeded = [
        SeededPair(
            pair_id,
            players,
            sum(points.get(p, 0.0) for p in players),
            min(positions.get(p) or UNRANKED for p in players),
        )
        for pair_id, players in pairs
    ]
    return sorted(seeded, key=lambda s: (-s.points, s.best_position, s.pair_id))


def slice_divisions(seeded):
    if len(seeded) % PAIRS_PER_DIVISION:
        raise Conflict(
            f"O número de parelhas ({len(seeded)}) não é múltiplo de {PAIRS_PER_DIVISION}.", "pairs_not_multiple_of_4"
        )
    return [seeded[i : i + PAIRS_PER_DIVISION] for i in range(0, len(seeded), PAIRS_PER_DIVISION)]


def _rounds(stage):
    existing = {r.number: r for r in Round.query.filter_by(stage_id=stage.id)}
    for n in range(1, len(ROUND_ROBIN) + 1):
        if n not in existing:
            existing[n] = Round(stage_id=stage.id, number=n)
            db.session.add(existing[n])
    db.session.flush()
    return existing


def build_divisions(stage, points=None, positions=None, with_fixtures=True):
    """Create the stage's groups, members (with pair) and round-robin matches.

    Returns [(group, [SeededPair, ...])]. The caller commits.
    """
    if not stage.pairing_closed:
        raise Conflict("Fecha primeiro as parelhas deste mini-torneio.", "pairing_not_closed")
    if CompetitionGroup.query.filter_by(stage_id=stage.id).first():
        raise Conflict("As divisões deste mini-torneio já foram criadas.", "divisions_exist")
    if points is None or positions is None:
        live_points, live_positions = ranking_svc.seeding(stage.competition.season.league_id)
        points = live_points if points is None else points
        positions = live_positions if positions is None else positions

    pairs = teams_pairing.stage_pairs(stage)
    entry_of = {}
    listed = []
    for pair in pairs:
        players = teams_pairing.pair_players(stage, pair)
        entry_of[pair.id] = (pair.entry_a_id, pair.entry_b_id)
        listed.append((pair.id, players))
    divisions = slice_divisions(seed_pairs(listed, points, positions))
    rounds = _rounds(stage) if with_fixtures else {}

    built = []
    for tier, division in enumerate(divisions, start=1):
        group = CompetitionGroup(stage_id=stage.id, tier=tier, name=f"{tier}.ª Divisão", rating=TEAMS_RATINGS.get(tier))
        db.session.add(group)
        db.session.flush()
        for seed, sp in enumerate(division, start=1):
            for entry_id in entry_of[sp.pair_id]:
                db.session.add(GroupMember(group_id=group.id, entry_id=entry_id, seed=seed, pair_id=sp.pair_id))
        if with_fixtures:
            for number, fixtures in enumerate(ROUND_ROBIN, start=1):
                for home, away in fixtures:
                    _add_match(group, rounds[number], division[home], division[away], entry_of)
        built.append((group, division))
    stage.status = "running" if stage.status == "planned" else stage.status
    db.session.flush()
    return built


def _add_match(group, rnd, home, away, entry_of):
    match = CompetitionMatch(
        group_id=group.id, round_id=rnd.id, status="scheduled", home_pair_id=home.pair_id, away_pair_id=away.pair_id
    )
    db.session.add(match)
    db.session.flush()
    for side, sp in (("home", home), ("away", away)):
        for slot, (entry_id, player_id) in enumerate(zip(entry_of[sp.pair_id], _players_of(entry_of[sp.pair_id])), 1):
            db.session.add(
                MatchParticipant(
                    match_id=match.id, side=side, slot=slot, role="member", entry_id=entry_id, player_id=player_id
                )
            )


def _players_of(entry_ids):
    rows = dict(db.session.query(Entry.id, Entry.player_id).filter(Entry.id.in_(entry_ids)).all())
    return [rows[e] for e in entry_ids]


# --- simulator ------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectedPair:
    pair_id: int | None  # None: not formed yet (would be formed at close)
    players: tuple
    points: float  # the two players' ranking points summed
    best_position: int | None
    formed_by: str  # mutual | manual | ranking | extra (the simulated pair)
    seed: int


@dataclass
class ProjectedDivision:
    tier: int
    name: str
    rating: int | None
    pairs: list = field(default_factory=list)
    points: float = 0.0  # the pairs' points summed


@dataclass
class Projection:
    stage_id: int
    pairing_closed: bool
    divisions: list
    extra_pair: tuple | None = None
    extra_pair_tier: int | None = None
    extra_pair_seed: int | None = None


def project(stage, extra_pair=None, now=None):
    """What close() + build_divisions() would give now, with `extra_pair` (a, b)
    as if they had just chosen each other. Same code paths, no writes.

    Raises teams_pairing.PairingError for a pair the rules refuse (pairs
    closed or the deadline passed, as declare(); not on the roster, already
    paired, 4th time together) and Conflict when the roster does not make
    whole divisions. Without extra_pair the board works after the deadline too.
    """
    extra = tuple(int(x) for x in extra_pair) if extra_pair is not None else None
    if extra is not None:
        teams_pairing.check_open(stage, now or datetime.utcnow())
    return _project(stage, extra, _Context.load(stage))


@dataclass
class _Context:
    """Everything a projection reads, loaded once per request."""

    points: dict
    positions: dict
    state: teams_pairing.PairingState
    existing: list  # [(pair_id, players, formed_by)]

    @classmethod
    def load(cls, stage):
        points, positions = teams_pairing.live_positions(stage)
        existing = [(p.id, teams_pairing.pair_players(stage, p), p.formed_by) for p in teams_pairing.stage_pairs(stage)]
        return cls(points, positions, teams_pairing.pairing_state(stage), existing)


def _project(stage, extra, ctx):
    listed = [(pid, players) for pid, players, _ in ctx.existing]
    formed_by = {pid: how for pid, _, how in ctx.existing}
    planned = []
    if not stage.pairing_closed:
        planned = teams_pairing.plan_close(stage, ctx.positions, extra, ctx.state)
    # Not-yet-formed pairs get ids after the existing ones, in creation order:
    # the order the real ids would have (seed_pairs breaks the last tie by id).
    next_id = max(formed_by, default=0)
    extra_id = None
    for i, (a, b, how) in enumerate(planned, start=1):
        listed.append((next_id + i, (a, b)))
        formed_by[next_id + i] = how
        if extra is not None and i == 1:
            extra_id, formed_by[next_id + i] = next_id + i, "extra"
    real_ids = {pid for pid, _, _ in ctx.existing}

    projection = Projection(stage.id, bool(stage.pairing_closed), [], extra)
    for tier, division in enumerate(slice_divisions(seed_pairs(listed, ctx.points, ctx.positions)), start=1):
        out = ProjectedDivision(tier, f"{tier}.ª Divisão", TEAMS_RATINGS.get(tier))
        for seed, sp in enumerate(division, start=1):
            out.pairs.append(
                ProjectedPair(
                    sp.pair_id if sp.pair_id in real_ids else None,
                    sp.players,
                    sp.points,
                    sp.best_position if sp.best_position != UNRANKED else None,
                    formed_by[sp.pair_id],
                    seed,
                )
            )
            if sp.pair_id == extra_id:
                projection.extra_pair_tier, projection.extra_pair_seed = tier, seed
        out.points = sum(p.points for p in out.pairs)
        projection.divisions.append(out)
    return projection


# --- partner simulator: every possible partner of one player --------------------


@dataclass(frozen=True)
class Placement:
    """Where a player's pair lands: tier, seed, partner and the pair's points."""

    partner_id: int | None
    tier: int | None
    seed: int | None
    points: float | None  # the pair's summed ranking points


@dataclass(frozen=True)
class Thresholds:
    """For a scenario in tier k: the weakest pair of tier k-1 (to move up) and
    the best pair of tier k+1 (to stay above). None at the edges."""

    tier: int | None
    weakest_above: float | None
    best_below: float | None


@dataclass(frozen=True)
class PartnerOption:
    player_id: int
    points: float  # b's own ranking points
    status: str  # unpaired | paired_with:<id> | declared_you | you_declared
    played_together: tuple  # stage numbers a and b already played together
    allowed: bool
    reason: str | None  # why not, when not allowed
    pair_points: float | None  # a + b
    tier: int | None
    seed: int | None
    delta_vs_baseline: float | None  # pair_points - baseline pair points


@dataclass
class PartnerSimulation:
    stage_id: int
    player_id: int
    player_points: float
    choice_open: bool
    baseline: Placement  # without a new choice (a's formed pair, or the auto partner)
    options: list  # [PartnerOption], by b's ranking position
    selected: int | None
    selected_placement: Placement | None
    thresholds: Thresholds | None  # for the selected scenario (else the baseline)


def _placement(projection, player_id):
    for division in projection.divisions:
        for pair in division.pairs:
            if player_id in pair.players:
                partner = next(p for p in pair.players if p != player_id)
                return Placement(partner, division.tier, pair.seed, pair.points)
    return Placement(None, None, None, None)


def _thresholds(projection, tier):
    if tier is None:
        return Thresholds(None, None, None)
    by_tier = {d.tier: d for d in projection.divisions}
    above, below = by_tier.get(tier - 1), by_tier.get(tier + 1)
    return Thresholds(
        tier,
        min(p.points for p in above.pairs) if above else None,
        max(p.points for p in below.pairs) if below else None,
    )


def _together_stages(stage, player_id):
    """{partner: (stage numbers)} of the player's pairs in the other stages."""
    from padel_league.models.v2 import Pair, Stage

    out = {}
    rows = (
        db.session.query(Pair, Stage.number)
        .join(Stage, Stage.id == Pair.stage_id)
        .filter(Stage.competition_id == stage.competition_id, Pair.stage_id != stage.id)
        .order_by(Stage.number)
    )
    for pair, number in rows:
        players = teams_pairing.pair_players(stage, pair)
        if player_id in players:
            other = players[0] if players[1] == player_id else players[1]
            out.setdefault(other, []).append(number)
    return {k: tuple(v) for k, v in out.items()}


def project_partners(stage, player_id, selected=None, now=None):
    """Every possible partner b of `player_id`: where a+b would land, from one
    ranking computation (each scenario is project(stage, (a, b)))."""
    a = int(player_id)
    ctx = _Context.load(stage)
    state = ctx.state
    if a not in state.roster:
        raise teams_pairing.PairingError("Esse jogador não está inscrito na Teams.")
    try:
        teams_pairing.check_open(stage, now or datetime.utcnow())
        closed_reason = None
    except teams_pairing.PairingError as exc:
        closed_reason = str(exc)

    baseline_projection = _project(stage, None, ctx)
    baseline = _placement(baseline_projection, a)
    together = _together_stages(stage, a)
    options, chosen = [], None
    others = sorted(state.roster - {a}, key=lambda p: (ctx.positions.get(p) or 10**9, p))
    for b in others:
        if b in state.paired_with:
            status = f"paired_with:{state.paired_with[b]}"
        elif state.choice.get(b) == a:
            status = "declared_you"
        elif state.choice.get(a) == b:
            status = "you_declared"
        else:
            status = "unpaired"
        reason, landed = closed_reason, None
        if reason is None:
            try:
                landed = _project(stage, (a, b), ctx)
            except (teams_pairing.PairingError, Conflict) as exc:
                reason = exc.message if isinstance(exc, Conflict) else str(exc)
        place = _placement(landed, a) if landed else None
        if landed and b == selected:
            chosen = landed
        options.append(
            PartnerOption(
                player_id=b,
                points=ctx.points.get(b, 0.0),
                status=status,
                played_together=together.get(b, ()),
                allowed=landed is not None,
                reason=reason,
                pair_points=place.points if place else None,
                tier=place.tier if place else None,
                seed=place.seed if place else None,
                delta_vs_baseline=(place.points - baseline.points) if place and baseline.points is not None else None,
            )
        )
    if chosen is not None:
        selected_placement = _placement(chosen, a)
        thresholds = _thresholds(chosen, selected_placement.tier)
    else:
        selected_placement = None
        thresholds = _thresholds(baseline_projection, baseline.tier)
    return PartnerSimulation(
        stage_id=stage.id,
        player_id=a,
        player_points=ctx.points.get(a, 0.0),
        choice_open=closed_reason is None,
        baseline=baseline,
        options=options,
        selected=int(selected) if selected is not None else None,
        selected_placement=selected_placement,
        thresholds=thresholds,
    )
