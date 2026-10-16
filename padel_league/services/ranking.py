"""The league ranking on v2: computed from awards by the season's ranking rule.

recompute() writes a RankingSnapshot (+ entries) and, until the old app is
deleted (phase 4), mirrors it into players.ranking_points / ranking_position,
which v1 and the Teams pairing still read. Points stay unrounded in v2; the
bigint mirror rounds half up, as the old column effectively did.

subs_ranking(): substitute points over the rule's subs window (default the
main ranking's window; domain.subs); compute() gives them, flagged source "subs", to players
without a counted award (art. 12).
"""

from dataclasses import dataclass
from datetime import date, datetime

from padel_league.domain import ranking as engine
from padel_league.domain import standings as rules
from padel_league.domain import subs as subs_rules
from padel_league.domain.errors import Conflict, NotFound
from padel_league.models import Player
from padel_league.models.v2 import (
    Award,
    AwardEvent,
    Competition,
    CompetitionGroup,
    CompetitionMatch,
    MatchParticipant,
    RankingEntry,
    RankingSnapshot,
    Season,
    Stage,
)
from padel_league.sql_db import db

# In-memory corrections of competition facts, {competition_id: {"status": .., "ends_on": ..}}.
# Empty: comp 26 (Shuffle 2025/26) got status/ends_on in migration f2b6c8d4a3e9.
COMPETITION_OVERRIDES = {}


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


def is_bootstrapped(league_id):
    """True once a ranking snapshot under the current season's rule exists."""
    try:
        rule = rule_for(league_id)
    except NotFound:
        return False
    latest = latest_snapshot(league_id)
    return latest is not None and latest.rule_id == rule.id


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
    fallback = _subs_fallback(rule, comps, awards)
    result = engine.compute(_engine_rule(rule), comps, awards, prev_positions, subs=fallback)
    awarded = {a.competition_id for a in awards}
    ended = {c.id for c in comps if c.status == "ended"}
    missing = [cid for cid in result.counted_competition_ids if cid in ended and cid not in awarded]
    if missing:
        raise Conflict(
            f"Faltam pontos de ranking das competições terminadas {missing}.", "ranking_missing_awards"
        )
    return result


@dataclass
class SubsRanking:
    competition_ids: list  # the competitions whose substitutes count
    lines: list  # [domain.subs.SubsLine]


SUBS_COUNTED_STATUSES = ("played", "walkover")
# ranking_rules.options["subs_window"]: "ranking" (default, Pedro 2026-10-16:
# every competition the main ranking counts) or "last_completed".
SUBS_WINDOWS = ("last_completed", "ranking")


def _subs_competitions(rule, comps, awards):
    window = (rule.options or {}).get("subs_window", "ranking")
    if window not in SUBS_WINDOWS:
        raise Conflict(f"Janela de pontos de substituto desconhecida: {window}.", "unknown_subs_window")
    if window == "ranking":
        counted = engine.counted_competitions(_engine_rule(rule), comps, awards)
        return [c for c in comps if c.id in counted]
    last = engine.last_completed(comps)
    return [last] if last else []


def _subs_lines(competitions):
    """[SubsLine] over the substitutes' matches in `competitions` (CompetitionFact),
    and {group_id: competition_id}."""
    by_id = {c.id: c for c in competitions}
    groups = (
        db.session.query(CompetitionGroup, Stage.competition_id)
        .join(Stage, Stage.id == CompetitionGroup.stage_id)
        .filter(Stage.competition_id.in_(list(by_id)))
        .all()
    )
    fmt = {g.id: by_id[cid].format for g, cid in groups}
    multipliers = {g.id: subs_rules.group_multiplier(fmt[g.id], g.tier, g.multiplier) for g, _ in groups}
    rows = (
        db.session.query(MatchParticipant.player_id, MatchParticipant.side, CompetitionMatch)
        .join(CompetitionMatch, CompetitionMatch.id == MatchParticipant.match_id)
        .filter(
            CompetitionMatch.group_id.in_(list(multipliers)),
            CompetitionMatch.status.in_(SUBS_COUNTED_STATUSES),
            MatchParticipant.role == "substitute",
            MatchParticipant.player_id.isnot(None),
        )
        .all()
    )
    facts, played = {}, []
    for player_id, side, match in rows:
        if match.id not in facts:
            sets = tuple(rules.SetResult(s.home_games, s.away_games, s.outcome) for s in sorted(match.sets, key=lambda s: s.set_no))
            walkover = match.walkover_winner if match.status == "walkover" else None
            facts[match.id] = rules.MatchFacts(0, (), (), sets, walkover)
        played.append(subs_rules.SubMatch(player_id, match.group_id, side, facts[match.id], fmt[match.group_id]))
    return subs_rules.subs_points(played, multipliers), {g.id: cid for g, cid in groups}


def _subs_explain(line, group_competition):
    return [
        engine.ExplainLine(
            competition_id=group_competition[group_id],
            stage_number=None,
            group_id=group_id,
            place=None,
            place_points=raw * (mult or 0),
            bonus_points=0.0,
            counted=True,
            reason=f"pontos de substituto (art. 12): {raw} × {mult or 0} em {n} jogo(s)",
        )
        for group_id, (raw, mult, n) in sorted(line.by_group.items())
    ]


def _member_ids(player_ids):
    """Players with status 'member' (external subs never enter the main ranking)."""
    if not player_ids:
        return set()
    rows = db.session.query(Player.id).filter(Player.id.in_(list(player_ids)), Player.status == "member")
    return {pid for (pid,) in rows}


def _subs_fallback(rule, comps, awards):
    """Art. 12: {player_id: (points, explain)} for members; compute() keeps those without a counted award."""
    lines, group_competition = _subs_lines(_subs_competitions(rule, comps, awards))
    members = _member_ids([l.player_id for l in lines])
    return {l.player_id: (l.points, _subs_explain(l, group_competition)) for l in lines if l.player_id in members}


def subs_ranking(league_id=1, rule=None):
    """Substitute points per player (members and external subs) in the rule's subs window."""
    rule = rule or rule_for(league_id)
    comps, awards = league_facts(league_id)
    competitions = _subs_competitions(rule, comps, awards)
    lines, _ = _subs_lines(competitions)
    return SubsRanking(sorted(c.id for c in competitions), lines)


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
    snapshot.entries = [RankingEntry(player_id=l.player_id, points=l.points, position=l.position, source=l.source) for l in result.lines]
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


def _same_lines(snapshot, result):
    """The snapshot still holds what compute() gives (substitute rows or a player's
    status can change it without a new award event)."""
    stored = {(e.player_id, round(e.points, 6), e.source) for e in snapshot.entries}
    return stored == {(l.player_id, round(l.points, 6), l.source) for l in result.lines}


def bootstrap(league_id=1):
    """Cut-over step, idempotent: award every ended Shuffle that has no awards,
    then write a ranking snapshot (and mirror players.*) unless the latest one
    already reflects the latest award event and still equals compute() (the
    substitutes import or a player becoming a member changes it without an
    award event). Returns a short report."""
    from padel_league.services import closeout

    report = []
    shuffles = (
        Competition.query.join(Season, Season.id == Competition.season_id)
        .filter(Season.league_id == league_id, Competition.format == "shuffle", Competition.status == "ended")
        .all()
    )
    for comp in shuffles:
        if not AwardEvent.query.filter_by(competition_id=comp.id).first():
            closeout.close_shuffle(comp.id, recompute_ranking=False)
            report.append(f"awarded shuffle {comp.id}")
    last_event = db.session.query(db.func.max(AwardEvent.id)).scalar()
    latest = latest_snapshot(league_id)
    rule = rule_for(league_id)
    if (
        latest
        and latest.rule_id == rule.id
        and latest.after_award_event_id == last_event
        and _same_lines(latest, compute(league_id, rule))
    ):
        report.append(f"ranking snapshot {latest.id} already current")
        return report
    snap = recompute(league_id, after_award_event_id=last_event, note="bootstrap-ranking")
    report.append(f"ranking snapshot {snap.id} written ({len(snap.entries)} players, rule {rule.key})")
    return report
