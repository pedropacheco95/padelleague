"""The league ranking on v2: computed from awards by the season's ranking rule.

recompute() writes a RankingSnapshot (+ entries) and, until the old app is
deleted (phase 4), mirrors it into players.ranking_points / ranking_position,
which v1 and the Teams pairing still read. Points stay unrounded in v2; the
bigint mirror rounds half up, as the old column effectively did.
"""

from datetime import date, datetime

from padel_league.domain import ranking as engine
from padel_league.domain.errors import Conflict, NotFound
from padel_league.models import Player
from padel_league.models.v2 import (
    Award,
    AwardEvent,
    Competition,
    RankingEntry,
    RankingSnapshot,
    Season,
    Stage,
)
from padel_league.sql_db import db

# FLAGGED ASSUMPTION (S0, 2026-10-15): the 2025/26 Shuffle (competition 26) has
# no dates and status 'running' in the data although all 10 jornadas ended.
# S0 fixes the status in a migration; its months are pending Pedro's answer.
# Treated as ended, between the 19ª and 21ª (its name, "20ª"). Today's window
# (last 3 completed) is the same whichever side of the 21ª it falls.
COMPETITION_OVERRIDES = {26: {"status": "ended", "ends_on": date(2026, 4, 30)}}


def _fact(c):
    over = COMPETITION_OVERRIDES.get(c.id, {})
    return engine.CompetitionFact(
        id=c.id,
        format=c.format,
        status=over.get("status", c.status),
        ends_on=c.ends_on or over.get("ends_on"),
        starts_on=c.starts_on,
        event_slot_id=c.event_slot_id,
    )


def current_season(league_id):
    return (
        Season.query.filter_by(league_id=league_id)
        .order_by(Season.starts_on.desc().nullslast(), Season.name.desc())
        .first()
    )


def rule_for(league_id):
    season = current_season(league_id)
    if season is None or season.ranking_rule is None:
        raise NotFound("Não há regra de ranking para a época atual.", "no_ranking_rule")
    return season.ranking_rule


def _engine_rule(rule):
    return engine.Rule(mode=rule.mode, last_n=rule.last_n, options=rule.options or {})


def league_facts(league_id):
    comps = Competition.query.join(Season, Season.id == Competition.season_id).filter(Season.league_id == league_id).all()
    comp_ids = [c.id for c in comps]
    rows = (
        db.session.query(Award, AwardEvent.competition_id, Stage.number)
        .join(AwardEvent, AwardEvent.id == Award.award_event_id)
        .outerjoin(Stage, Stage.id == AwardEvent.stage_id)
        .filter(AwardEvent.competition_id.in_(comp_ids))
        .all()
    )
    awards = [
        engine.AwardFact(
            player_id=a.player_id,
            competition_id=comp_id,
            place_points=a.place_points,
            bonus_points=a.bonus_points,
            place=a.place,
            group_id=a.group_id,
            stage_number=stage_number,
        )
        for a, comp_id, stage_number in rows
    ]
    return [_fact(c) for c in comps], awards


def latest_snapshot(league_id, include_dry_runs=False):
    q = RankingSnapshot.query.filter_by(league_id=league_id)
    if not include_dry_runs:
        q = q.filter_by(is_dry_run=False)
    return q.order_by(RankingSnapshot.id.desc()).first()


def current_snapshot(league_id=1):
    return latest_snapshot(league_id)


def compute(league_id, rule=None):
    """The ranking as it stands now (nothing written).

    Refuses when a completed competition in the window has no awards (e.g. the
    2025/26 Shuffle before closeout.close_shuffle ran): a silent gap would seed
    Teams with the wrong numbers.
    """
    rule = rule or rule_for(league_id)
    comps, awards = league_facts(league_id)
    previous = latest_snapshot(league_id)
    prev_positions = {e.player_id: e.position for e in previous.entries} if previous else {}
    result = engine.compute(_engine_rule(rule), comps, awards, prev_positions)
    awarded = {a.competition_id for a in awards}
    ended = {c.id for c in comps if c.status == "ended"}
    missing = [cid for cid in result.counted_competition_ids if cid in ended and cid not in awarded]
    if missing:
        raise Conflict(
            f"Faltam pontos de ranking das competições terminadas {missing}.", "ranking_missing_awards"
        )
    return result


def seeding(league_id):
    """(points, positions) by player under the live ranking: seeds Teams pairing and divisions."""
    result = compute(league_id)
    return {l.player_id: l.points for l in result.lines}, {l.player_id: l.position for l in result.lines}


def recompute(league_id, after_award_event_id=None, note=None, dry_run=False, mirror=True):
    """Write a new snapshot from the current awards; returns it."""
    rule = rule_for(league_id)
    result = compute(league_id, rule)
    snapshot = RankingSnapshot(
        league_id=league_id,
        rule_id=rule.id,
        after_award_event_id=after_award_event_id,
        computed_at=datetime.utcnow(),
        is_dry_run=dry_run,
        note=note,
    )
    snapshot.entries = [RankingEntry(player_id=l.player_id, points=l.points, position=l.position) for l in result.lines]
    db.session.add(snapshot)
    if mirror and not dry_run:
        mirror_into_players(result)
    db.session.flush()
    return snapshot


def mirror_into_players(result):
    """Old columns: bigint points (half up). Every player who was ranked before
    keeps a nonzero position after the ranked ones (v1 recomputes the ranking
    with the old rule whenever a recent player has position 0)."""
    by_player = {l.player_id: l for l in result.lines}
    players = Player.query.all()
    for player in players:
        line = by_player.get(player.id)
        player.ranking_points = int(line.points + 0.5) if line else 0
    position = len(result.lines)
    rest = sorted(
        (p for p in players if p.id not in by_player and (p.ranking_position or 0) > 0),
        key=lambda p: (p.ranking_position, p.id),
    )
    for player in players:
        if player.id in by_player:
            player.ranking_position = by_player[player.id].position
    for player in rest:
        position += 1
        player.ranking_position = position


def explain(player_id, league_id=1):
    """Every award of the player and whether it counts now, with the reason."""
    return compute(league_id).explain.get(player_id, [])
