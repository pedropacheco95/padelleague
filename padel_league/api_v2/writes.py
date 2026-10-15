"""Result entry, absences, group close-out, Teams divisions and Shuffle rounds.

Any signed-in player enters results and absences (admins only once a group has
ended); the rest is admin. All domain work is S1's services (results, closeout,
teams_divisions, shuffle); this module validates input and maps errors.
"""

import logging

from flask import Blueprint, jsonify

from padel_league.models import Player
from padel_league.models.v2 import Absence, CompetitionGroup, CompetitionMatch, GroupMember, Round, Stage
from padel_league.services import closeout, results, shuffle, teams_divisions
from padel_league.services.results import ResultError
from padel_league.sql_db import db

from . import serializers as ser
from ._http import (
    bad_request,
    conflict,
    has_role,
    int_arg,
    json_body,
    not_found,
    register_error_handlers,
    require_user,
    role_required,
)
from .cards import CardData
from .competitions import competition_detail, get_competition
from .matches import get_group, group_detail, match_query, serialize_matches

bp = Blueprint("api_v2_writes", __name__, url_prefix="/api/v2")
register_error_handlers(bp)

SET_OUTCOMES = ("completed", "timeout_draw", "not_started")


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


def _guard_closed(group, user):
    """An ended group's results belong to the admins: editing reopens it (S0, 15 Oct)."""
    if group.has_ended and not has_role(user, "admin"):
        raise conflict("Este grupo já terminou; só um admin pode alterar resultados.", "group_closed")


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
    _guard_closed(match.group, user)

    try:
        results.record_sets(match.id, sets=sets, walkover_winner=walkover, court=court, actor_user_id=user.id)
    except ResultError as exc:
        db.session.rollback()
        raise bad_request(str(exc), "invalid_result")
    db.session.commit()
    try:
        # Closes the group once its last result lands (snapshot → awards → ranking); commits.
        results.after_result_commit(match.group)
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
    _guard_closed(group, user)
    entry = results._member_entry(group_id, player_id)
    if entry is None:
        raise bad_request("O jogador não pertence a este grupo.", "not_a_member")
    if substitute_id is not None and substitute_id == player_id:
        raise bad_request("O substituto não pode ser o próprio jogador.", "invalid_input")
    match_ids = data.get("matchIds")
    if match_ids is not None:
        if not isinstance(match_ids, list) or not match_ids:
            raise bad_request("matchIds tem de ser uma lista de jogos.", "invalid_input")
        match_ids = [int_arg(m, "matchIds", required=True) for m in match_ids]
    if kind == "partial" and not match_ids:
        raise bad_request("Uma falta parcial indica os jogos (matchIds).", "match_ids_required")

    results.mark_absent(
        group_id,
        rnd.number,
        player_id,
        actor_user_id=user.id,
        substitute_player_id=substitute_id,
        match_ids=match_ids if kind == "partial" else None,
    )
    absence = Absence.query.filter_by(entry_id=entry.id, round_id=rnd.id).first()
    if absence is None:  # the group has no matches in this round
        absence = Absence(entry_id=entry.id, round_id=rnd.id, kind=kind, source="recorded", created_by_user_id=user.id)
        db.session.add(absence)
    db.session.commit()
    substitute = db.session.get(Player, substitute_id) if substitute_id else None
    return jsonify(ser.absence(absence, group_id, substitute, user.player)), 201


@bp.route("/absences/<int:absence_id>", methods=["DELETE"])
@role_required("player")
def delete_absence(absence_id):
    """Undo a recorded absence (S1 results.undo_absence: the member gets their slot back
    in the round's unplayed matches). Migrated (derived) absences are history."""
    absence = db.session.get(Absence, absence_id)
    if absence is None:
        raise not_found("Falta não encontrada.", "absence_not_found")
    if absence.source != "recorded":
        raise conflict("Esta falta vem do histórico e não pode ser anulada aqui.", "absence_not_recorded")
    user = require_user()
    rnd_groups = (
        CompetitionGroup.query.join(GroupMember, GroupMember.group_id == CompetitionGroup.id)
        .filter(GroupMember.entry_id == absence.entry_id, CompetitionGroup.stage_id == absence.round.stage_id)
        .all()
    )
    for group in rnd_groups:
        _guard_closed(group, user)
    results.undo_absence(absence.id, actor_user_id=user.id)
    db.session.commit()
    return "", 204


@bp.route("/groups/<int:group_id>/close", methods=["POST"])
@role_required("admin")
def close_group(group_id):
    user = require_user()
    group = get_group(group_id)
    # S1: standings snapshot → awards → ranking snapshot + mirror. Conflict
    # group_not_complete / group_already_closed → 409.
    closeout.close_group(group.id, actor_user_id=user.id)
    db.session.commit()
    db.session.expire_all()
    return jsonify(group_detail(get_group(group_id)))


@bp.route("/stages/<int:stage_id>/divisions", methods=["POST"])
@role_required("admin")
def build_divisions(stage_id):
    """Teams: form a mini-tournament's divisions (pairs by summed ranking points, 4 per division)."""
    stage = db.session.get(Stage, stage_id)
    if stage is None:
        raise not_found("Mini-torneio não encontrado.", "stage_not_found")
    if stage.competition.format != "teams":
        raise conflict("Só a Teams forma divisões por parelhas.", "not_teams")
    teams_divisions.build_divisions(stage)
    db.session.commit()
    db.session.expire_all()
    stage = db.session.get(Stage, stage_id)
    data = CardData([stage.competition])
    return jsonify(ser.stage(stage, groups=data.groups.get(stage.id, []), images=data.images))


def _shuffle(competition_id):
    comp = get_competition(competition_id)
    if comp.format != "shuffle":
        raise conflict("Só a Shuffle tem jornadas geradas.", "not_shuffle")
    return comp


def _competition_page(competition_id):
    db.session.expire_all()
    return jsonify(competition_detail(get_competition(competition_id)))


@bp.route("/competitions/<int:competition_id>/rounds", methods=["POST"])
@role_required("admin")
def shuffle_next_round(competition_id):
    """Shuffle: the next round's groups from the overall standings (S1 services.shuffle)."""
    _shuffle(competition_id)
    shuffle.generate_round(competition_id)
    db.session.commit()
    return _competition_page(competition_id)


@bp.route("/competitions/<int:competition_id>/rounds", methods=["DELETE"])
@role_required("admin")
def shuffle_delete_round(competition_id):
    _shuffle(competition_id)
    shuffle.delete_last_round(competition_id)
    db.session.commit()
    return _competition_page(competition_id)
