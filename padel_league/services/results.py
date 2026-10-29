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
    """Validate the submitted sets for the competition format.

    Returns (MatchSet rows, complete). Teams: 1 to 3 sets; fewer than 3, all
    `completed`, is a result in progress (saved set by set, not complete yet);
    a time-out chain (timeout_draw + not_started) always sends the 3 sets.
    Clássica/Shuffle: exactly one completed set, always complete.
    """
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
        if not parsed or len(parsed) > rules.TEAMS_SETS_PER_MATCH:
            raise InvalidInput("Um encontro da Teams tem 1 a 3 sets.", "teams_needs_three_sets")
        for result in parsed:
            rules.set_points(result)  # raises on a completed set without a winner
        complete = len(parsed) == rules.TEAMS_SETS_PER_MATCH
        if not complete and any(r.outcome != "completed" for r in parsed):
            raise InvalidInput("Com tempo esgotado envia os 3 sets.", "teams_needs_three_sets")
    else:
        if len(parsed) != 1 or parsed[0].outcome != "completed":
            raise InvalidInput("Este formato regista um só set terminado.", "one_set_expected")
        if parsed[0].home_games is None or parsed[0].away_games is None:
            raise InvalidInput("Indica os jogos das duas equipas.", "invalid_set_score")
        complete = True
    rows = [
        MatchSet(set_no=n, home_games=r.home_games, away_games=r.away_games, outcome=r.outcome)
        for n, r in enumerate(parsed, start=1)
    ]
    return rows, complete


def is_in_progress(match):
    """A Teams result saved set by set and not complete: sets stored, status still scheduled."""
    return match.status == "scheduled" and bool(match.sets)


def record_sets(match_id, sets=(), walkover_winner=None, court=None, actor_user_id=None):
    """Record a result: the sets (Teams: 1 to 3, complete at 3; Clássica/Shuffle: 1) or a
    walkover (Teams only: the present pair wins 3-0, no sets are stored).

    A Teams result with 1 or 2 completed sets is saved in progress: the sets are
    stored and shown, but the match stays `scheduled`, so nothing counts it
    (standings, close-out, awards, ranking, projection all key on the status)
    until the 3rd set arrives. Absences and seats are untouched either way."""
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
        new_sets, complete = _set_rows(fmt, sets)
        status = "played" if complete else "scheduled"

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


def clear_result(match_id, actor_user_id=None):
    """Undo a result saved by mistake: the match goes back to scheduled with no sets.
    Absences stay (they are undone on their own)."""
    match = db.session.get(CompetitionMatch, match_id)
    if match is None:
        raise NotFound(f"Jogo {match_id} não existe.", "match_not_found")
    before = _match_state(match)
    for old in list(match.sets):
        match.sets.remove(old)
        db.session.delete(old)
    match.status = "scheduled"
    match.walkover_winner = None
    match.updated_by_user_id = actor_user_id
    match.updated_at = datetime.utcnow()
    unfreeze_group_standings(match.group_id)
    _audit(actor_user_id, "match", match.id, "result_cleared", before, _match_state(match))
    return match


def _member_entry(group_id, player_id):
    return (
        Entry.query.join(GroupMember, GroupMember.entry_id == Entry.id)
        .filter(GroupMember.group_id == group_id, Entry.player_id == player_id)
        .first()
    )


def mark_absent(group_id, round_number, player_id, actor_user_id=None, substitute_player_id=None, match_ids=None):
    """Remove a player from the matches of a round in a group and record the absence.

    Every match of the round by default (kind 'full'); only `match_ids` when
    given (kind 'partial': the player misses some matches of the jornada).
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
    kind = "full"
    if match_ids is not None:
        wanted = {int(m) for m in match_ids}
        if not wanted or not wanted <= {m.id for m in matches}:
            raise InvalidInput("Escolhe jogos desta jornada.", "matches_not_in_round")
        matches = [m for m in matches if m.id in wanted]
        kind = "partial"
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
        played_affected = played_affected or has_result(match)
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
                    kind=kind,
                    source="recorded",
                    created_by_user_id=actor_user_id,
                )
            )
        else:
            absence.kind = "full" if "full" in (kind, absence.kind) else kind
            absence.source = "recorded"

    if played_affected:
        unfreeze_group_standings(group_id)
    return removed, played_affected


def _removal(match, player_id):
    """The audit event that took the member out of `match` (latest first), or None."""
    events = (
        AuditEvent.query.filter_by(entity="match", entity_id=match.id, action="absence")
        .order_by(AuditEvent.id.desc())
        .all()
    )
    for event in events:
        for p in (event.before or {}).get("participants", []):
            if p.get("player_id") == player_id and p.get("role") == "member":
                return event, (p["side"], p["slot"])
    return None


def _slot_before_absence(match, player_id):
    """(side, slot) the player held before they were marked absent, from the audit trail."""
    found = _removal(match, player_id)
    return found[1] if found else None


def undo_absence(absence_id, actor_user_id=None):
    """Put the player back in the matches of the round they were taken out of and
    delete the absence.

    Unplayed matches always. A match with a result only when the player was taken
    out of it AFTER the result was saved (a correction, e.g. the wrong player
    marked): undoing gives them their slot, set points and presence back. A match
    that was played with the substitute (marked before, e.g. the player arrived
    late) keeps the substitute, and the absence stays as a partial one so the
    record matches the seat. The slot comes from the audit trail of the absence;
    a substitute in that slot is removed. Returns the number of matches restored.
    """
    absence = db.session.get(Absence, absence_id)
    if absence is None:
        raise NotFound(f"Ausência {absence_id} não existe.", "absence_not_found")
    if absence.source == "derived":
        raise InvalidInput("Esta ausência vem dos resultados e não pode ser anulada.", "absence_derived")
    entry = absence.entry
    group_ids = [gm.group_id for gm in GroupMember.query.filter_by(entry_id=entry.id)]
    matches = CompetitionMatch.query.filter(
        CompetitionMatch.round_id == absence.round_id, CompetitionMatch.group_id.in_(group_ids)
    ).all()
    restored, touched_groups, kept_out = 0, set(), False
    for match in matches:
        if any(p.player_id == entry.player_id for p in _participants(match.id)):
            continue
        found = _removal(match, entry.player_id)
        if found is None:
            continue
        removed_after_result = (found[0].before or {}).get("status") in ("played", "walkover")
        if has_result(match) and not removed_after_result:
            kept_out = True  # played with the substitute: that stands
            continue
        if _restore_member(match, entry, actor_user_id, action="absence_undone"):
            restored += 1
            if has_result(match):
                touched_groups.add(match.group_id)
        else:
            kept_out = True
    action = "narrowed" if kept_out else "deleted"
    _audit(actor_user_id, "absence", absence_id, action, {"entry_id": entry.id, "round_id": absence.round_id})
    if kept_out:
        absence.kind = "partial"
    else:
        db.session.delete(absence)
    for group_id in touched_groups:
        unfreeze_group_standings(group_id)
    return restored


def has_result(match):
    """A saved result (played or walkover): its participants count in the standings."""
    return match.status in ("played", "walkover")


def _participants(match_id):
    # Query the rows: match.participants can be stale in the session (Do-Not-Repeat 2026-10-16).
    return MatchParticipant.query.filter_by(match_id=match_id).all()


def _restore_member(match, entry, actor_user_id, action):
    """Give `entry`'s player back the slot they held in `match` before an absence.

    False when they already play it, no absence took them out of it, or a member
    holds that slot now (left to an admin)."""
    rows = _participants(match.id)
    if any(p.player_id == entry.player_id for p in rows):
        return False
    place = _slot_before_absence(match, entry.player_id)
    if place is None:
        return False
    side, slot = place
    occupant = next((p for p in rows if p.side == side and p.slot == slot), None)
    if occupant is not None and occupant.role == "member":
        return False
    before = _match_state(match)
    if occupant is not None:
        if occupant in match.participants:
            match.participants.remove(occupant)
        db.session.delete(occupant)
        db.session.flush()
    match.participants.append(
        MatchParticipant(side=side, slot=slot, role="member", entry_id=entry.id, player_id=entry.player_id)
    )
    db.session.flush()
    _audit(actor_user_id, "match", match.id, action, before, _match_state(match))
    return True


def _absent_member_of_slot(match, side, slot, rows):
    """The group member who held (side, slot) before an absence and is not back in the match."""
    playing = {p.player_id for p in rows}
    events = (
        AuditEvent.query.filter_by(entity="match", entity_id=match.id, action="absence")
        .order_by(AuditEvent.id.desc())
        .all()
    )
    for event in events:
        for p in (event.before or {}).get("participants", []):
            if p.get("side") == side and p.get("slot") == slot and p.get("role") == "member":
                if p.get("player_id") in playing:
                    return None
                return _member_entry(match.group_id, p.get("player_id"))
    return None


def set_slot(match_id, side, slot, player_id, actor_user_id=None):
    """Say who played in one seat of one match (the per-player control of the result modal).

    - The seat holds a member and `player_id` is someone else (or None = unknown
      substitute): the member missed this match, recorded as a partial absence
      with that substitute (`mark_absent` for this match only).
    - The seat holds a substitute (or nobody) and `player_id` is the member who
      was taken out of it: the member is put back (undo for this match); the
      absence goes once the member plays every match of the round again.
    - Otherwise the substitute in the seat is replaced (None = unknown).

    Works before and after the result is saved; returns True when a match with a
    result changed (callers refresh the standings of a closed group).
    """
    match = db.session.get(CompetitionMatch, match_id)
    if match is None:
        raise NotFound("Jogo não encontrado.", "match_not_found")
    if side not in ("home", "away") or slot not in (1, 2):
        raise InvalidInput("Lugar inválido.", "invalid_slot")
    if match.status == "cancelled":
        raise InvalidInput("Este jogo foi cancelado.", "match_cancelled")
    rows = _participants(match.id)
    occupant = next((p for p in rows if p.side == side and p.slot == slot), None)
    if occupant is not None and occupant.player_id == player_id:
        return False
    if player_id is not None and any(p.player_id == player_id for p in rows):
        raise InvalidInput("Esse jogador já está neste jogo.", "already_in_match")

    if occupant is not None and occupant.role == "member":
        if player_id is not None and _member_entry(match.group_id, player_id) is not None:
            raise InvalidInput("Esse jogador é do grupo; não pode ser substituto.", "substitute_is_member")
        mark_absent(
            match.group_id,
            match.round.number,
            occupant.player_id,
            actor_user_id=actor_user_id,
            substitute_player_id=player_id,
            match_ids=[match.id],
        )
        return has_result(match)

    original = _absent_member_of_slot(match, side, slot, rows)
    if player_id is not None and original is not None and original.player_id == player_id:
        _restore_member(match, original, actor_user_id, action="absence_undone")
        _settle_absence(match, original)
        if has_result(match):
            unfreeze_group_standings(match.group_id)
            return True
        return False

    if player_id is not None and _member_entry(match.group_id, player_id) is not None:
        raise InvalidInput("Esse jogador é do grupo; não pode ser substituto.", "substitute_is_member")
    before = _match_state(match)
    if occupant is not None:
        if occupant in match.participants:
            match.participants.remove(occupant)
        db.session.delete(occupant)
        db.session.flush()
    if player_id is not None:
        match.participants.append(MatchParticipant(side=side, slot=slot, role="substitute", player_id=player_id))
        db.session.flush()
    # Same audit action as mark_absent, so a later restore still finds the member's seat.
    _audit(actor_user_id, "match", match.id, "absence", before, _match_state(match))
    return False  # substitutes score nothing: standings unchanged


def _settle_absence(match, entry):
    """After a member is put back in `match`: drop the round's absence if they now play
    every match of the round they were taken out of, else it is a partial one."""
    absence = Absence.query.filter_by(entry_id=entry.id, round_id=match.round_id).first()
    if absence is None:
        return
    group_ids = [gm.group_id for gm in GroupMember.query.filter_by(entry_id=entry.id)]
    others = CompetitionMatch.query.filter(
        CompetitionMatch.round_id == match.round_id, CompetitionMatch.group_id.in_(group_ids)
    ).all()
    still_out = [
        m
        for m in others
        if not any(p.player_id == entry.player_id for p in _participants(m.id))
        and _slot_before_absence(m, entry.player_id) is not None
    ]
    if still_out:
        absence.kind = "partial"
    else:
        db.session.delete(absence)


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
    """Close the group if complete (awards before the ranking: B1 fixed), or,
    for a group closed earlier, refresh its snapshot, awards and the ranking so
    an edited result never leaves them stale. Commits."""
    from padel_league.services import closeout

    if group.has_ended:
        if not StandingSnapshot.query.join(GroupMember, GroupMember.id == StandingSnapshot.group_member_id).filter(
            GroupMember.group_id == group.id
        ).first():  # unfrozen by an edit
            closeout.refresh_closed_group(group.id)
            db.session.commit()
        return
    if close_group_if_complete(group):
        db.session.commit()
