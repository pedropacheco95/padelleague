"""Shuffle on v2: overall order, next-round divisions, round generation.

A Shuffle is a competition whose stages are its jornadas; each stage has one
round and one group per division (tier), with the division's multiplier.
Rules kept from the old shuffle code (shuffle_tournaments.py and the v1
shuffle endpoints):
- overall order: points (3 × multiplier a win, 1 × a draw), presences, games
  difference, general ranking points, then a stable draw (sha256 of
  "<tournament id>:<player id>", tournament id = the pre-v2 shuffle id);
- next round: 8 per division in that order, the last division takes the rest;
- in a division of 8 (in overall order) the pairs are 1–8, 2–7, 3–6, 4–5 and
  every pair plays every other once (6 matches).
"""

import hashlib

from padel_league.domain.errors import Conflict, NotFound
from padel_league.models import Player
from padel_league.models.v2 import (
    Competition,
    CompetitionGroup,
    CompetitionMatch,
    Entry,
    GroupMember,
    MatchParticipant,
    Round,
    Stage,
)
from padel_league.sql_db import db

SLOTS_PER_DIVISION = 8
PAIRS = [(0, 7), (1, 6), (2, 5), (3, 4)]
PAIR_MATCHUPS = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
DEFAULT_MULTIPLIERS = {1: 10, 2: 8, 3: 6, 4: 5, 5: 4, 6: 3}


def _competition(competition_id):
    competition = db.session.get(Competition, competition_id)
    if competition is None or competition.format != "shuffle":
        raise NotFound(f"Shuffle {competition_id} não existe.", "competition_not_found")
    return competition


def draw_order(competition, player_id):
    tournament_id = competition.legacy_shuffle_id or competition.id
    return int(hashlib.sha256(f"{tournament_id}:{player_id}".encode("utf-8")).hexdigest()[:12], 16)


def number_of_divisions(competition):
    return max(1, int((competition.rules or {}).get("number_of_divisions") or 6))


def multipliers(competition):
    raw = (competition.rules or {}).get("division_multipliers") or {}
    return {int(k): int(v) for k, v in raw.items()} or dict(DEFAULT_MULTIPLIERS)


def overall_order(competition, rows):
    """Sort CompetitionRows (services.standings) by the Shuffle rule and set place / next_group_tier."""
    points = dict(
        db.session.query(Player.id, Player.ranking_points).filter(Player.id.in_([r.player_id for r in rows])).all()
    )
    ordered = sorted(
        rows,
        key=lambda r: (
            -r.points,
            -r.appearances,
            -r.games_difference,
            -(points.get(r.player_id) or 0),
            draw_order(competition, r.player_id),
        ),
    )
    divisions = number_of_divisions(competition)
    for index, row in enumerate(ordered):
        row.place = index + 1
        row.next_group_tier = min(index // SLOTS_PER_DIVISION + 1, divisions)
    return ordered


def next_divisions(competition_id):
    """{tier: [entry_id]} for the next round, in overall order."""
    from padel_league.services.standings import competition_standings

    competition = _competition(competition_id)
    rows = overall_order(competition, competition_standings(competition_id).rows)
    out = {}
    for row in rows:
        out.setdefault(row.next_group_tier, []).append(row.entry_id)
    return out


def _unfinished(competition_id):
    return (
        CompetitionMatch.query.join(CompetitionGroup, CompetitionGroup.id == CompetitionMatch.group_id)
        .join(Stage, Stage.id == CompetitionGroup.stage_id)
        .filter(Stage.competition_id == competition_id, CompetitionMatch.status == "scheduled")
        .count()
    )


def generate_round(competition_id, on=None, actor_user_id=None):
    """Create the next jornada: a stage with one round and a group per division.

    Divisions with fewer than 8 players get no matches (as before). Returns the
    stage. Refuses while any match of the Shuffle is unplayed. Caller commits.
    """
    competition = _competition(competition_id)
    if _unfinished(competition_id):
        raise Conflict("Há jogos por jogar; termina a jornada antes de gerar a seguinte.", "round_unfinished")
    divisions = next_divisions(competition_id)
    if not any(len(ids) >= SLOTS_PER_DIVISION for ids in divisions.values()):
        raise Conflict("Nenhuma divisão tem 8 jogadores.", "not_enough_players")

    for stage in competition.stages:
        stage.status = "ended"
    number = max((s.number for s in competition.stages), default=0) + 1
    stage = Stage(competition_id=competition.id, number=number, seeding_method="standings", status="running")
    db.session.add(stage)
    db.session.flush()
    rnd = Round(stage_id=stage.id, number=1, date=on)
    db.session.add(rnd)
    db.session.flush()

    players = dict(db.session.query(Entry.id, Entry.player_id).filter(Entry.competition_id == competition.id).all())
    mult = multipliers(competition)
    for tier in sorted(divisions):
        entry_ids = divisions[tier]
        group = CompetitionGroup(stage_id=stage.id, tier=tier, multiplier=mult.get(tier, 1), structure="round_robin")
        db.session.add(group)
        db.session.flush()
        for seed, entry_id in enumerate(entry_ids, start=1):
            db.session.add(GroupMember(group_id=group.id, entry_id=entry_id, seed=seed))
        if len(entry_ids) < SLOTS_PER_DIVISION:
            continue
        seats = entry_ids[:SLOTS_PER_DIVISION]
        pairs = [(seats[a], seats[b]) for a, b in PAIRS]
        for home, away in PAIR_MATCHUPS:
            match = CompetitionMatch(group_id=group.id, round_id=rnd.id, status="scheduled")
            db.session.add(match)
            db.session.flush()
            for side, pair in (("home", pairs[home]), ("away", pairs[away])):
                for slot, entry_id in enumerate(pair, start=1):
                    db.session.add(
                        MatchParticipant(
                            match_id=match.id, side=side, slot=slot, role="member",
                            entry_id=entry_id, player_id=players[entry_id],
                        )
                    )  # fmt: skip
    rules = dict(competition.rules or {})
    rules["current_matchweek"] = number
    competition.rules = rules
    competition.status = "running"
    db.session.flush()
    return stage


def delete_last_round(competition_id):
    """Undo the latest jornada while none of its matches has been played."""
    competition = _competition(competition_id)
    if not competition.stages:
        raise Conflict("Esta Shuffle ainda não tem jornadas.", "no_rounds")
    last = max(competition.stages, key=lambda s: s.number)
    played = (
        CompetitionMatch.query.join(CompetitionGroup, CompetitionGroup.id == CompetitionMatch.group_id)
        .filter(CompetitionGroup.stage_id == last.id, CompetitionMatch.status != "scheduled")
        .count()
    )
    if played:
        raise Conflict("A última jornada já tem resultados.", "round_has_results")
    for group in list(last.groups):
        CompetitionMatch.query.filter_by(group_id=group.id).delete(synchronize_session=False)
    db.session.delete(last)
    db.session.flush()
    previous = max((s for s in competition.stages if s.id != last.id), key=lambda s: s.number, default=None)
    if previous is not None:
        previous.status = "running"
    rules = dict(competition.rules or {})
    rules["current_matchweek"] = previous.number if previous else 0
    competition.rules = rules
    return previous
