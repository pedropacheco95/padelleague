"""Result entry, absences and group close-out. Any signed-in player enters results and
absences; closing a group is admin. The domain work is S1's (services.results.record_sets,
services.closeout.close_group); older service paths cover Clássica/Shuffle until then.
"""

import logging

from flask import Blueprint, jsonify

from padel_league.models.v2 import (
    Absence,
    GroupMember,
    AuditEvent,
    CompetitionGroup,
    CompetitionMatch,
    MatchParticipant,
    Round,
)
from padel_league.services import results
from padel_league.services.results import ResultError
from padel_league.sql_db import db

from . import serializers as ser
from ._http import (
    bad_request,
    conflict,
    int_arg,
    json_body,
    not_found,
    register_error_handlers,
    require_user,
    role_required,
)
from .matches import get_group, group_detail, match_query, serialize_matches

bp = Blueprint("api_v2_writes", __name__, url_prefix="/api/v2")
register_error_handlers(bp)

SET_OUTCOMES = ("completed", "timeout_draw", "not_started")


def _service(module, name):
    try:
        mod = __import__(f"padel_league.services.{module}", fromlist=[name])
    except ImportError:
        return None
    return getattr(mod, name, None)


def _parse_sets(raw):
    if not isinstance(raw, list) or len(raw) > 3:
        raise bad_request("sets tem de ser uma lista com até 3 sets.")
    sets = []
    for s in raw:
        if not isinstance(s, dict) or s.get("outcome") not in SET_OUTCOMES:
            raise bad_request("Cada set precisa de um outcome válido.", "invalid_set")
        sets.append(
            {
                "home_games": int_arg(s.get("homeGames"), "homeGames"),
                "away_games": int_arg(s.get("awayGames"), "awayGames"),
                "outcome": s["outcome"],
            }
        )
    return sets


def _close_if_complete(group):
    """v1 closes a division as its last result lands; keep that behaviour."""
    close_group = _service("closeout", "close_group")
    if close_group is not None:
        if all(m.status in ("played", "walkover") for m in group.matches):
            try:
                close_group(group.id)
                db.session.commit()
            except Exception as exc:  # noqa: BLE001 - a Conflict (already closed) is fine here
                if type(exc).__name__ != "Conflict":
                    raise
                db.session.rollback()
        return
    if group.stage.competition.format == "classica":
        results.after_result_commit(group)


@bp.route("/matches/<int:match_id>/result", methods=["PUT"])
@role_required("player")
def put_result(match_id):
    user = require_user()
    match = db.session.get(CompetitionMatch, match_id)
    if match is None:
        raise not_found("Jogo não encontrado.", "match_not_found")
    data = json_body()
    sets = _parse_sets(data.get("sets", []))
    walkover = data.get("walkoverWinner")
    if walkover not in (None, "home", "away"):
        raise bad_request("walkoverWinner inválido.", "invalid_input")
    court = data.get("court")
    fmt = match.group.stage.competition.format

    record_sets = _service("results", "record_sets")
    try:
        if record_sets is not None:
            record_sets(match.id, sets=sets, walkover_winner=walkover, court=court, actor_user_id=user.id)
        elif walkover is None and fmt != "teams" and len(sets) == 1 and sets[0]["outcome"] == "completed":
            s = sets[0]
            if s["home_games"] is None or s["away_games"] is None:
                raise bad_request("Indica os jogos das duas equipas.", "invalid_set_score")
            results.record_result(match.id, s["home_games"], s["away_games"], court=court, actor_user_id=user.id)
        else:
            raise conflict("Este tipo de resultado ainda não está disponível.", "not_available")
    except ResultError as exc:
        db.session.rollback()
        raise bad_request(str(exc), "invalid_result")
    db.session.commit()
    try:
        _close_if_complete(match.group)
    except Exception:  # noqa: BLE001 - the result is saved; v1 also logs and carries on
        db.session.rollback()
        logging.getLogger(__name__).exception("close-out after result on match %s failed", match_id)
    fresh = match_query().filter(CompetitionMatch.id == match_id).one()
    return jsonify(serialize_matches([fresh])[0])


@bp.route("/rounds/<int:round_id>/absences", methods=["POST"])
@role_required("player")
def post_absence(round_id):
    user = require_user()
    rnd = db.session.get(Round, round_id)
    if rnd is None:
        raise not_found("Jornada não encontrada.", "round_not_found")
    data = json_body()
    player_id = int_arg(data.get("playerId"), "playerId", required=True)
    group_id = int_arg(data.get("groupId"), "groupId", required=True)
    substitute_id = int_arg(data.get("substitutePlayerId"), "substitutePlayerId")
    kind = data.get("kind", "full")
    if kind not in ("full", "partial"):
        raise bad_request("kind inválido.", "invalid_input")
    group = db.session.get(CompetitionGroup, group_id)
    if group is None or group.stage_id != rnd.stage_id:
        raise bad_request("O grupo não pertence a esta jornada.", "invalid_input")
    entry = results._member_entry(group_id, player_id)
    if entry is None:
        raise bad_request("O jogador não pertence a este grupo.", "not_a_member")
    if substitute_id is not None and substitute_id == player_id:
        raise bad_request("O substituto não pode ser o próprio jogador.", "invalid_input")

    results.mark_absent(group_id, rnd.number, player_id, actor_user_id=user.id, substitute_player_id=substitute_id)
    absence = Absence.query.filter_by(entry_id=entry.id, round_id=rnd.id).first()
    if absence is None:  # the group has no matches in this round
        absence = Absence(entry_id=entry.id, round_id=rnd.id, kind=kind, source="recorded", created_by_user_id=user.id)
        db.session.add(absence)
    absence.kind = kind
    db.session.commit()
    from padel_league.models import Player

    substitute = db.session.get(Player, substitute_id) if substitute_id else None
    return jsonify(ser.absence(absence, group_id, substitute)), 201


@bp.route("/absences/<int:absence_id>", methods=["DELETE"])
@role_required("player")
def delete_absence(absence_id):
    """Undo a recorded absence: the player gets their slot back in every match of that
    round where the absence moved them out (from the audit trail), then the record goes.
    Migrated (derived) absences are history and are not deleted here."""
    absence = db.session.get(Absence, absence_id)
    if absence is None:
        raise not_found("Falta não encontrada.", "absence_not_found")
    if absence.source != "recorded":
        raise conflict("Esta falta vem do histórico e não pode ser anulada aqui.", "absence_not_recorded")
    entry = absence.entry
    group_ids = [m.group_id for m in GroupMember.query.filter_by(entry_id=entry.id)]
    matches = CompetitionMatch.query.filter(
        CompetitionMatch.round_id == absence.round_id, CompetitionMatch.group_id.in_(group_ids)
    ).all()
    for match in matches:
        if any(p.player_id == entry.player_id for p in match.participants):
            continue
        audit = (
            AuditEvent.query.filter_by(entity="match", entity_id=match.id, action="absence")
            .order_by(AuditEvent.id.desc())
            .all()
        )
        slot = next(
            (
                (p["side"], p["slot"])
                for a in audit
                for p in (a.before or {}).get("participants", [])
                if p["player_id"] == entry.player_id
            ),
            None,
        )
        if slot is None:
            continue
        occupant = next((p for p in match.participants if (p.side, p.slot) == slot), None)
        if occupant is not None:
            if occupant.role == "member":  # someone else holds it now; leave it alone
                continue
            match.participants.remove(occupant)
            db.session.delete(occupant)
            db.session.flush()
        match.participants.append(
            MatchParticipant(side=slot[0], slot=slot[1], role="member", entry_id=entry.id, player_id=entry.player_id)
        )
        if match.status in ("played", "walkover"):
            results.unfreeze_group_standings(match.group_id)
    db.session.delete(absence)
    db.session.commit()
    return "", 204


@bp.route("/groups/<int:group_id>/close", methods=["POST"])
@role_required("admin")
def close_group(group_id):
    user = require_user()
    group = get_group(group_id)
    close = _service("closeout", "close_group")
    if close is not None:
        close(group.id, actor_user_id=user.id)
        db.session.commit()
    else:
        if group.stage.competition.format != "classica":
            raise conflict("O fecho deste formato ainda não está disponível.", "not_available")
        if group.has_ended:
            raise conflict("Este grupo já está fechado.", "group_already_closed")
        if not results.close_group_if_complete(group):
            raise conflict("Ainda há jogos por jogar neste grupo.", "group_not_complete")
        db.session.commit()
        if group.stage.competition.format == "classica":
            from padel_league.models import League

            db.session.expire_all()
            League.query.first().update_rankings()
    db.session.expire_all()
    return jsonify(group_detail(get_group(group_id)))

