"""Write paths for match results and absences on the v2 model.

Every function changes facts only (matches, sets, participants, absences) and
records an audit event, all in the caller's transaction; callers commit.
Live standings need no recompute: they are computed from these facts by the
views. A group whose standings were frozen at migration gets them unfrozen
when one of its results is edited, as the old code recomputed them too.
"""

from datetime import datetime

from padel_league.models.v2 import (
    Absence,
    AuditEvent,
    CompetitionMatch,
    Entry,
    GroupMember,
    MatchParticipant,
    StandingSnapshot,
)
from padel_league.sql_db import db


class ResultError(ValueError):
    pass


def _audit(actor_user_id, entity, entity_id, action, before=None, after=None):
    db.session.add(
        AuditEvent(
            actor_user_id=actor_user_id,
            entity=entity,
            entity_id=entity_id,
            action=action,
            before=before,
            after=after,
        )
    )


def _match_state(match):
    first = next((s for s in match.sets if s.set_no == 1), None)
    return {
        "status": match.status,
        "court": match.court,
        "home_games": first.home_games if first else None,
        "away_games": first.away_games if first else None,
        "participants": [
            {"side": p.side, "slot": p.slot, "player_id": p.player_id, "role": p.role}
            for p in match.participants
        ],
    }


def unfreeze_group_standings(group_id):
    """Drop a finished group's frozen rows so its standings are recomputed live."""
    member_ids = [gm.id for gm in GroupMember.query.filter_by(group_id=group_id)]
    if member_ids:
        StandingSnapshot.query.filter(StandingSnapshot.group_member_id.in_(member_ids)).delete(
            synchronize_session=False
        )


def record_result(match_id, home_games, away_games, court=None, actor_user_id=None):
    match = db.session.get(CompetitionMatch, match_id)
    if match is None:
        raise ResultError(f"match {match_id} not found")
    before = _match_state(match)

    if court is not None:
        match.court = court
    if home_games is not None and away_games is not None:
        match.set_score(int(home_games), int(away_games))
        match.status = "played"
    elif home_games is not None or away_games is not None:
        first = next((s for s in match.sets if s.set_no == 1), None)
        match.set_score(
            int(home_games) if home_games is not None else (first.home_games if first else None),
            int(away_games) if away_games is not None else (first.away_games if first else None),
        )
    match.updated_by_user_id = actor_user_id
    match.updated_at = datetime.utcnow()

    if match.status == "played":
        unfreeze_group_standings(match.group_id)
    _audit(actor_user_id, "match", match.id, "result", before, _match_state(match))
    return match


def _member_entry(group_id, player_id):
    return (
        Entry.query.join(GroupMember, GroupMember.entry_id == Entry.id)
        .filter(GroupMember.group_id == group_id, Entry.player_id == player_id)
        .first()
    )


def mark_absent(group_id, round_number, player_id, actor_user_id=None, substitute_player_id=None):
    """Remove a player from every match of a round in a group and record the absence.

    The slot they leave is filled by `substitute_player_id` when given,
    otherwise it stays unknown (shown as "Substituto"). Returns
    (removed_count, any_played_match_affected).
    """
    matches = (
        CompetitionMatch.query.filter_by(group_id=group_id)
        .join(CompetitionMatch.round)
        .filter_by(number=round_number)
        .all()
    )
    removed, played_affected = 0, False
    for match in matches:
        participant = next((p for p in match.participants if p.player_id == player_id), None)
        if participant is None:
            continue
        before = _match_state(match)
        side, slot = participant.side, participant.slot
        db.session.delete(participant)
        match.participants.remove(participant)
        if substitute_player_id:
            db.session.flush()
            match.participants.append(
                MatchParticipant(side=side, slot=slot, role="substitute", player_id=substitute_player_id)
            )
        removed += 1
        played_affected = played_affected or match.played
        _audit(actor_user_id, "match", match.id, "absence", before, _match_state(match))

    entry = _member_entry(group_id, player_id)
    if entry is not None and matches:
        round_id = matches[0].round_id
        absence = Absence.query.filter_by(entry_id=entry.id, round_id=round_id).first()
        if absence is None:
            db.session.add(
                Absence(
                    entry_id=entry.id,
                    round_id=round_id,
                    kind="full",
                    source="recorded",
                    created_by_user_id=actor_user_id,
                )
            )
        else:
            absence.kind, absence.source = "full", "recorded"

    if played_affected:
        unfreeze_group_standings(group_id)
    return removed, played_affected


def match_for_shuffle_id(shuffle_match_id):
    """Shuffle matches keep their pre-v2 ids in the API; newer ones use the v2 id."""
    match = CompetitionMatch.query.filter_by(legacy_shuffle_match_id=shuffle_match_id).first()
    return match or db.session.get(CompetitionMatch, shuffle_match_id)


def _group_standings(group_id):
    """Standings of a classica group from the compat view (frozen or live)."""
    rows = db.session.execute(
        db.text(
            "select player_id, place, wins, draws from compat.players_in_division "
            "where division_id = :g order by place"
        ),
        {"g": group_id},
    ).all()
    return rows


def close_group_if_complete(group):
    """Mark a group ended once every match is played and write its ranking awards.

    Returns True when the group was closed by this call. The caller commits and
    then recomputes the ranking, so the closing group always counts (the old
    code recomputed before marking the division ended).
    """
    from padel_league.models.v2 import Award, AwardEvent

    if group.has_ended:
        return False
    matches = CompetitionMatch.query.filter_by(group_id=group.id).all()
    if not matches or any(not m.played for m in matches):
        return False

    last = max((m.scheduled_at for m in matches if m.scheduled_at), default=None)
    group.has_ended = True
    group.end_date = datetime.combine(last.date(), datetime.min.time()) if last else None
    group.standings_up_to_date = True

    competition = group.stage.competition
    if not group.open_division and group.rating:
        event = AwardEvent(
            competition_id=competition.id,
            stage_id=group.stage_id,
            group_id=group.id,
            awarded_at=datetime.utcnow(),
            source="computed",
        )
        db.session.add(event)
        for player_id, place, wins, draws in _group_standings(group.id):
            entry = Entry.query.filter_by(competition_id=competition.id, player_id=player_id).first()
            entry.final_place = place
            event.awards.append(
                Award(
                    entry_id=entry.id,
                    player_id=player_id,
                    group_id=group.id,
                    place=place,
                    rating=group.rating,
                    place_points=float(int(group.rating * 0.75 ** (place - 1))),
                    bonus_points=wins * (group.rating / 100) + draws * (group.rating / 250),
                    wins=wins,
                    draws=draws,
                )
            )
    _audit(None, "group", group.id, "closed", None, {"end_date": str(group.end_date)})
    return True


def after_result_commit(group):
    """Close the group if complete and refresh the ranking. Commits."""
    from padel_league.models import League

    if close_group_if_complete(group):
        db.session.commit()
        db.session.expire_all()
        League.query.first().update_rankings()
