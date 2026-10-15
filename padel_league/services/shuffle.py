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
    StandingSnapshot,
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


def competition_for_tournament_id(tournament_id):
    """The v2 competition behind a v1 shuffle tournament id (pre-v2 id first, then the v2 id)."""
    competition = Competition.query.filter_by(format="shuffle", legacy_shuffle_id=tournament_id).first()
    competition = competition or Competition.query.filter_by(format="shuffle", id=tournament_id).first()
    if competition is None:
        raise NotFound(f"Shuffle {tournament_id} não existe.", "competition_not_found")
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


def _live_rows(competition_id):
    from padel_league.services.standings import competition_standings

    return competition_standings(competition_id).rows


def _division_rows(competition):
    """The competition-level standing rows: the calculated division (next_division)
    and position (place) of every entry, as v1 stored them on the relation."""
    return {
        s.entry_id: s
        for s in StandingSnapshot.query.join(Entry, Entry.id == StandingSnapshot.entry_id).filter(
            Entry.competition_id == competition.id, StandingSnapshot.group_member_id.is_(None)
        )
    }


def _row_for(competition, entry_id, rows):
    row = rows.get(entry_id)
    if row is None:
        row = StandingSnapshot(entry_id=entry_id, group_member_id=None, source="computed")
        db.session.add(row)
        rows[entry_id] = row
    return row


def next_divisions(competition_id):
    """{tier: [entry_id]} for the next round.

    The calculated divisions when every entry has one (v1: calculate_divisions,
    then generate), seated within a division in the live overall order;
    otherwise straight from the live overall order.
    """
    competition = _competition(competition_id)
    rows = overall_order(competition, _live_rows(competition_id))  # sets live place
    stored = _division_rows(competition)
    if rows and all(r.entry_id in stored and stored[r.entry_id].next_division for r in rows):
        # v1 rewrote the stored position with the live order on every read and
        # admin action, so within a division the seats follow the live order.
        out = {}
        for row in sorted(rows, key=lambda r: (r.place, -(r.points or 0), r.player_id)):
            out.setdefault(stored[row.entry_id].next_division, []).append(row.entry_id)
        return out
    out = {}
    for row in rows:
        out.setdefault(row.next_group_tier, []).append(row.entry_id)
    return out


def calculate_divisions(competition_id):
    """Store every entry's next division and position from the live overall order."""
    competition = _competition(competition_id)
    stored = _division_rows(competition)
    for row in overall_order(competition, _live_rows(competition_id)):
        snap = _row_for(competition, row.entry_id, stored)
        snap.place, snap.next_division = row.place, row.next_group_tier
    db.session.flush()


def _last_played_tier(competition, entry_id):
    row = (
        db.session.query(CompetitionGroup.tier)
        .join(CompetitionMatch, CompetitionMatch.group_id == CompetitionGroup.id)
        .join(MatchParticipant, MatchParticipant.match_id == CompetitionMatch.id)
        .join(Stage, Stage.id == CompetitionGroup.stage_id)
        .filter(Stage.competition_id == competition.id, MatchParticipant.entry_id == entry_id,
                CompetitionMatch.status == "played")
        .order_by(Stage.number.desc(), CompetitionMatch.id.desc())
        .first()
    )  # fmt: skip
    return row[0] if row else None


def undo_calculate_divisions(competition_id):
    """Put everyone back in the division they last played in (v1 undo)."""
    competition = _competition(competition_id)
    live = {r.entry_id: r for r in _live_rows(competition_id)}
    stored = _division_rows(competition)
    divisions = number_of_divisions(competition)
    fallback_order = sorted(
        live.values(),
        key=lambda r: ((stored.get(r.entry_id).place if r.entry_id in stored else None) or 9999,
                       -(r.points or 0), r.player_id),
    )  # fmt: skip
    fallback = {r.entry_id: min(i // SLOTS_PER_DIVISION + 1, divisions) for i, r in enumerate(fallback_order)}
    for entry_id in live:
        snap = _row_for(competition, entry_id, stored)
        snap.next_division = _last_played_tier(competition, entry_id) or fallback.get(entry_id, snap.next_division or 1)
    reordered = sorted(
        live.values(),
        key=lambda r: (stored[r.entry_id].next_division or 9999, stored[r.entry_id].place or 9999,
                       -(r.points or 0), r.player_id),
    )  # fmt: skip
    for index, r in enumerate(reordered, start=1):
        stored[r.entry_id].place = index
    db.session.flush()


def create_shuffle(title, players, number_of_divisions=6, max_players=48, multipliers_by_tier=None,
                   has_ended=False, season_id=None):
    """players: [(player_id, order_index)]. Division = (order_index-1)//8 + 1 (capped)."""
    from padel_league.services.ranking import current_season

    if season_id is None:
        season = current_season(1)
        season_id = season.id if season else None
    competition = Competition(
        season_id=season_id, format="shuffle", name=title, title=title, status="running",
        rules={"current_matchweek": 0, "max_players": max_players, "number_of_divisions": number_of_divisions,
               "has_ended": has_ended,
               "division_multipliers": {str(k): v for k, v in (multipliers_by_tier or DEFAULT_MULTIPLIERS).items()}},
    )  # fmt: skip
    db.session.add(competition)
    db.session.flush()
    for player_id, order_index in sorted(players, key=lambda x: x[1]):
        entry = Entry(competition_id=competition.id, player_id=player_id)
        db.session.add(entry)
        db.session.flush()
        db.session.add(
            StandingSnapshot(
                entry_id=entry.id, group_member_id=None, source="computed", place=order_index,
                next_division=min((order_index - 1) // SLOTS_PER_DIVISION + 1, number_of_divisions),
            )
        )  # fmt: skip
    db.session.flush()
    return competition


def remove_player_from_round(competition_id, stage_number, player_id, actor_user_id=None):
    """The player misses a jornada: out of every match of that stage, absence recorded."""
    from padel_league.services import results

    competition = _competition(competition_id)
    stage = Stage.query.filter_by(competition_id=competition.id, number=stage_number).first()
    if stage is None:
        raise NotFound("Não há jogos nessa jornada.", "round_not_found")
    removed = 0
    for group in stage.groups:
        n, _ = results.mark_absent(group.id, 1, player_id, actor_user_id=actor_user_id)
        removed += n
    if not removed:
        raise NotFound("O jogador não está nessa jornada.", "player_not_in_round")
    return removed


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
    if competition.status == "ended":
        raise Conflict("Esta Shuffle já terminou.", "competition_ended")
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
