"""Close-out on v2: group complete → snapshot standings → awards → ranking snapshot.

The order fixes B1: the old code recomputed the ranking before marking the
division ended, so the closing division counted 0. Here the awards are
written (and flushed) before the ranking is recomputed. Callers commit.
"""

from datetime import datetime

from padel_league.domain import awards as points
from padel_league.domain.errors import Conflict, NotFound
from padel_league.models.v2 import (
    AuditEvent,
    Award,
    AwardEvent,
    Competition,
    CompetitionGroup,
    CompetitionMatch,
    Entry,
    GroupMember,
    StandingSnapshot,
)
from padel_league.services import ranking
from padel_league.services import standings as standings_svc
from padel_league.sql_db import db

DONE = ("played", "walkover", "cancelled")


def group_rating(group):
    """Teams groups use the Teams ratings by tier unless the group sets its own."""
    if group.rating:
        return group.rating
    if group.stage.competition.format == "teams":
        return points.TEAMS_RATINGS.get(group.tier)
    return None


def is_complete(group_id):
    statuses = [s for (s,) in db.session.query(CompetitionMatch.status).filter_by(group_id=group_id)]
    return bool(statuses) and all(s in DONE for s in statuses)


def snapshot_standings(group, rows):
    members = {gm.entry_id: gm.id for gm in GroupMember.query.filter_by(group_id=group.id)}
    StandingSnapshot.query.filter(StandingSnapshot.group_member_id.in_(list(members.values()))).delete(
        synchronize_session=False
    )
    rounds = standings_svc.rounds_played(group.id)
    for r in rows:
        db.session.add(
            StandingSnapshot(
                entry_id=r.entry_id,
                group_member_id=members[r.entry_id],
                place=r.place,
                points=r.points,
                appearances=r.appearances,
                percentage_of_appearances=r.attendance_pct,
                wins=r.wins,
                draws=r.draws,
                losses=r.losses,
                games_played=r.appearances,
                games_won=r.games_won,
                games_lost=r.games_lost,
                matchweek=rounds,
                source="computed",
            )
        )


def write_group_awards(group, rows, now):
    rating = group_rating(group)
    if group.open_division or not rating:
        return None
    competition = group.stage.competition
    event = AwardEvent(
        competition_id=competition.id, stage_id=group.stage_id, group_id=group.id, awarded_at=now, source="computed"
    )
    db.session.add(event)
    for line in points.group_awards(rows, rating):
        event.awards.append(
            Award(
                entry_id=line.entry_id,
                player_id=line.player_id,
                group_id=group.id,
                place=line.place,
                rating=rating,
                place_points=line.place_points,
                bonus_points=line.bonus_points,
                wins=line.wins,
                draws=line.draws,
            )
        )
        if competition.format == "classica":
            db.session.get(Entry, line.entry_id).final_place = line.place
    db.session.flush()
    return event


def _roll_up(group, now):
    """Stage ends when all its groups did; the competition when all its stages did."""
    stage = group.stage
    if all(g.has_ended for g in stage.groups):
        stage.status = "ended"
        competition = stage.competition
        if all(s.status == "ended" for s in competition.stages):
            competition.status = "ended"
            competition.ends_on = competition.ends_on or now.date()


def close_group(group_id, actor_user_id=None, now=None, recompute_ranking=True):
    """Close a finished group. Returns the award event (None for open/unrated groups)."""
    now = now or datetime.utcnow()
    group = db.session.get(CompetitionGroup, group_id)
    if group is None:
        raise NotFound(f"Grupo {group_id} não existe.", "group_not_found")
    if group.has_ended:
        raise Conflict("Este grupo já está fechado.", "group_already_closed")
    if not is_complete(group_id):
        raise Conflict("Ainda há jogos por jogar neste grupo.", "group_not_complete")

    rows = standings_svc.compute_rows(group)
    snapshot_standings(group, rows)
    event = write_group_awards(group, rows, now)

    last = (
        db.session.query(db.func.max(CompetitionMatch.scheduled_at)).filter_by(group_id=group_id).scalar()
    )
    group.has_ended = True
    group.end_date = datetime.combine(last.date(), datetime.min.time()) if last else now
    group.standings_up_to_date = True
    _roll_up(group, now)
    db.session.add(
        AuditEvent(actor_user_id=actor_user_id, entity="group", entity_id=group.id, action="closed",
                   after={"end_date": str(group.end_date), "award_event_id": event.id if event else None})
    )
    db.session.flush()
    if recompute_ranking and event is not None:
        league_id = group.stage.competition.season.league_id
        ranking.recompute(league_id, after_award_event_id=event.id, note=f"group {group.id} closed")
    return event


def close_shuffle(competition_id, actor_user_id=None, now=None, recompute_ranking=True):
    """Shuffle awards: the curve over the final overall places (no bonus).

    Overall places come from the competition-level standing rows
    (standing_snapshots with no group member).
    """
    now = now or datetime.utcnow()
    competition = db.session.get(Competition, competition_id)
    if competition is None or competition.format != "shuffle":
        raise NotFound(f"Shuffle {competition_id} não existe.", "competition_not_found")
    if AwardEvent.query.filter_by(competition_id=competition_id).first():
        raise Conflict("Esta Shuffle já tem pontos de ranking atribuídos.", "already_awarded")
    rows = (
        db.session.query(StandingSnapshot, Entry.player_id)
        .join(Entry, Entry.id == StandingSnapshot.entry_id)
        .filter(Entry.competition_id == competition_id, StandingSnapshot.group_member_id.is_(None))
        .all()
    )
    if not rows or any(s.place is None for s, _ in rows):
        raise Conflict("A classificação final da Shuffle não está completa.", "shuffle_not_complete")
    event = AwardEvent(competition_id=competition_id, awarded_at=now, source="computed")
    db.session.add(event)
    for snap, player_id in rows:
        event.awards.append(
            Award(
                entry_id=snap.entry_id,
                player_id=player_id,
                place=snap.place,
                place_points=points.shuffle_place_points(snap.place),
                bonus_points=0.0,
                wins=snap.wins or 0,
                draws=snap.draws or 0,
            )
        )
        db.session.get(Entry, snap.entry_id).final_place = snap.place
    db.session.flush()
    if recompute_ranking:
        ranking.recompute(competition.season.league_id, after_award_event_id=event.id, note=f"shuffle {competition_id} awarded")
    return event
