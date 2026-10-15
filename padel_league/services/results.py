"""Write paths for match results and absences on the v2 model.

Every function changes facts only (matches, sets, participants, absences) and
records an audit event, all in the caller's transaction; callers commit.
Live standings need no recompute: they are computed from these facts by the
views. A group whose standings were frozen at migration gets them unfrozen
when one of its results is edited, as the old code recomputed them too.
"""

from datetime import datetime

from padel_league.domain import standings as rules
from padel_league.domain.errors import InvalidInput, NotFound
from padel_league.models.v2 import (
    Absence,
    AuditEvent,
    CompetitionMatch,
    Entry,
    MatchSet,
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
        "sets": [[x.home_games, x.away_games, x.outcome] for x in match.sets],
        "walkover_winner": match.walkover_winner,
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


def _set_rows(fmt, sets):
    """Validate the submitted sets for the competition format; returns MatchSet rows."""
    parsed = []
    for raw in sets:
        outcome = raw.get("outcome") or "completed"
        home, away = raw.get("home_games"), raw.get("away_games")
        parsed.append(
            rules.SetResult(
                int(home) if home is not None else None, int(away) if away is not None else None, outcome
            )
        )
    if fmt == "teams":
        if len(parsed) != rules.TEAMS_SETS_PER_MATCH:
            raise InvalidInput("Um encontro da Teams tem sempre exatamente 3 sets.", "teams_needs_three_sets")
        for result in parsed:
            rules.set_points(result)  # raises on a completed set without a winner
    else:
        if len(parsed) != 1 or parsed[0].outcome != "completed":
            raise InvalidInput("Este formato regista um só set terminado.", "one_set_expected")
        if parsed[0].home_games is None or parsed[0].away_games is None:
            raise InvalidInput("Indica os jogos das duas equipas.", "invalid_set_score")
    return [
        MatchSet(set_no=n, home_games=r.home_games, away_games=r.away_games, outcome=r.outcome)
        for n, r in enumerate(parsed, start=1)
    ]


def record_sets(match_id, sets=(), walkover_winner=None, court=None, actor_user_id=None):
    """Record a full result: the sets (Teams: exactly 3; Clássica/Shuffle: 1) or a
    walkover (Teams only: the present pair wins 3-0, no sets are stored)."""
    match = db.session.get(CompetitionMatch, match_id)
    if match is None:
        raise NotFound(f"Jogo {match_id} não existe.", "match_not_found")
    fmt = match.group.stage.competition.format
    before = _match_state(match)

    if walkover_winner is not None:
        if fmt != "teams":
            raise InvalidInput("Só a Teams regista faltas de comparência.", "walkover_not_allowed")
        if walkover_winner not in ("home", "away"):
            raise InvalidInput("Vencedor de falta de comparência inválido.", "invalid_walkover")
        if sets:
            raise InvalidInput("Uma falta de comparência não tem sets.", "walkover_has_no_sets")
        new_sets, status = [], "walkover"
    else:
        new_sets, status = _set_rows(fmt, sets), "played"

    for old in list(match.sets):
        match.sets.remove(old)
        db.session.delete(old)
    db.session.flush()
    match.sets.extend(new_sets)
    match.status = status
    match.walkover_winner = walkover_winner
    if court is not None:
        match.court = court
    match.updated_by_user_id = actor_user_id
    match.updated_at = datetime.utcnow()
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


def close_group_if_complete(group):
    """Close the group once every match is done: snapshot, awards, ranking (in that order).

    Returns True when this call closed it. The caller commits.
    """
    from padel_league.services import closeout

    if group.has_ended or not closeout.is_complete(group.id):
        return False
    closeout.close_group(group.id)
    return True


def after_result_commit(group):
    """Close the group if complete (awards before the ranking: B1 fixed). Commits."""
    if close_group_if_complete(group):
        db.session.commit()
