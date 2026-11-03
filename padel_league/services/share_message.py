"""Teams WhatsApp jornada message: which jornada the current weekly window offers, and whether an
admin already copied it (Pedro and Dudas, 2 Nov: admins only copy the message, never read it).

Window: opens every Wednesday at 00:01 Europe/Lisbon (DST-aware through zoneinfo; tzdata is a main
dependency) and lasts until the next one. Tuesday 23:59 and Wednesday 00:00 still belong to the
previous window.

Jornada of a window: walk the competition's rounds in (mini-torneio number, round number) order and
take the one right after the last FINISHED round. A round is finished when its night is before the
window's Wednesday, or when it already has a saved result. The night is Round.date, else the Lisbon
date of its earliest scheduled match, the same chain lib/teamsShareMessage uses for the header. So
dated rounds follow the calendar, undated ones follow results (a Tuesday result saved late on
Wednesday does not re-offer the jornada just played, since the button follows the date), and a mix
of both works. No round after the last finished one, or one with no matches yet (the next
mini-torneio before its divisions exist): no message, round None.

Copied: an append-only audit_events row (entity "competition", action "share_copied") written at or
after the window start for the same round. Shared by every admin; no migration.
"""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import case, func

from padel_league.domain.errors import Conflict
from padel_league.models.v2 import AuditEvent, CompetitionMatch, Round, Stage
from padel_league.sql_db import db

LISBON = ZoneInfo("Europe/Lisbon")
OPENS_AT = time(0, 1)
WEDNESDAY = 2  # date.weekday()
ENTITY, ACTION = "competition", "share_copied"
WITH_RESULT = ("played", "walkover")


def window_start(now=None):
    """The start of the window `now` (naive UTC) is in, as an aware Lisbon datetime."""
    now = now or datetime.utcnow()
    local = now.replace(tzinfo=timezone.utc).astimezone(LISBON)
    day = local.date() - timedelta(days=(local.weekday() - WEDNESDAY) % 7)
    start = datetime.combine(day, OPENS_AT, tzinfo=LISBON)
    if start > local:  # Wednesday 00:00-00:01: still last week's window
        start = datetime.combine(day - timedelta(days=7), OPENS_AT, tzinfo=LISBON)
    return start


def _utc_naive(aware):
    return aware.astimezone(timezone.utc).replace(tzinfo=None)


def _night(rnd, first_scheduled):
    if rnd.date is not None:
        return rnd.date
    if first_scheduled is not None:
        return first_scheduled.replace(tzinfo=timezone.utc).astimezone(LISBON).date()
    return None


def round_rows(competition_id):
    """[(round, stage number, night date or None, live matches, matches with a result)] in order."""
    stats = {
        rid: (first, live, done)
        for rid, first, live, done in db.session.query(
            CompetitionMatch.round_id,
            func.min(CompetitionMatch.scheduled_at),
            func.sum(case((CompetitionMatch.status != "cancelled", 1), else_=0)),
            func.sum(case((CompetitionMatch.status.in_(WITH_RESULT), 1), else_=0)),
        )
        .join(Round, Round.id == CompetitionMatch.round_id)
        .join(Stage, Stage.id == Round.stage_id)
        .filter(Stage.competition_id == competition_id)
        .group_by(CompetitionMatch.round_id)
    }
    rows = (
        db.session.query(Round, Stage.number)
        .join(Stage, Stage.id == Round.stage_id)
        .filter(Stage.competition_id == competition_id)
        .order_by(Stage.number, Round.number)
        .all()
    )
    out = []
    for rnd, stage_number in rows:
        first, live, done = stats.get(rnd.id, (None, 0, 0))
        out.append((rnd, stage_number, _night(rnd, first), int(live or 0), int(done or 0)))
    return out


def window_round(competition_id, start):
    """The round the window starting at `start` (aware Lisbon) offers, or None."""
    wednesday = start.date()
    rows = round_rows(competition_id)
    last_finished = -1
    for i, (_rnd, _n, night, _live, done) in enumerate(rows):
        if (night is not None and night < wednesday) or done:
            last_finished = i
    if last_finished + 1 >= len(rows):
        return None
    rnd, stage_number, night, live, _done = rows[last_finished + 1]
    if not live:
        return None
    return {"round": rnd, "stage_number": stage_number, "night": night}


def _copies(competition_id, since_utc):
    return (
        AuditEvent.query.filter(
            AuditEvent.entity == ENTITY,
            AuditEvent.entity_id == competition_id,
            AuditEvent.action == ACTION,
            AuditEvent.at >= since_utc,
        )
        .order_by(AuditEvent.id.desc())
        .all()
    )


def state(competition_id, now=None):
    start = window_start(now)
    target = window_round(competition_id, start)
    copy = None
    if target is not None:
        rid = target["round"].id
        copy = next((e for e in _copies(competition_id, _utc_naive(start)) if (e.after or {}).get("roundId") == rid), None)
    return {"window_start": start, "target": target, "copy": copy}


def record_copy(competition_id, round_id, actor_user_id, now=None):
    """An admin copied the message of `round_id`. Refused (409) when that is no longer the window's
    round (a stale tab). Copying twice in a window keeps the first record."""
    now = now or datetime.utcnow()
    current = state(competition_id, now)
    target = current["target"]
    if target is None or target["round"].id != round_id:
        raise Conflict("Esta já não é a mensagem da jornada atual. Recarrega a página.", "share_round_changed")
    if current["copy"] is None:
        db.session.add(
            AuditEvent(
                actor_user_id=actor_user_id,
                entity=ENTITY,
                entity_id=competition_id,
                action=ACTION,
                at=now,
                after={
                    "roundId": round_id,
                    "stageId": target["round"].stage_id,
                    "round": target["round"].number,
                    "windowStart": current["window_start"].isoformat(),
                },
            )
        )
        db.session.flush()
    return state(competition_id, now)
