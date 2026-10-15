from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, verify_jwt_in_request

from padel_league.models import Player
from padel_league.services import teams_pairing
from padel_league.services.teams_pairing import PairingError
from padel_league.sql_db import db
from padel_league.tools.auth_tools import admin_required_jwt, jwt_user

from .serializers import serialize_player_short

bp = Blueprint("api_v1_teams", __name__, url_prefix="/api/v1/teams")


def _viewer():
    try:
        verify_jwt_in_request(optional=True)
    except Exception:  # noqa: BLE001 - an expired or bad token just means "anonymous" here
        return None
    return jwt_user()


def _state(mt, viewer=None):
    players = sorted(teams_pairing.roster_players(mt), key=teams_pairing.ranking_key)
    pairs = teams_pairing.stage_pairs(mt)
    pair_players = {p.id: teams_pairing.pair_players(mt, p) for p in pairs}
    paired = {pid for ids in pair_players.values() for pid in ids}
    by_id = {p.id: p for p in players}
    my_id = viewer.player_id if viewer else None
    in_roster = my_id in by_id

    my_choice, chose_me = None, []
    if in_roster:
        my_choice = teams_pairing.choice_of(mt, my_id)
        chose_me = [pid for pid in teams_pairing.chose(mt, my_id) if pid not in paired]

    history = teams_pairing.times_together(mt)
    source = {"mutual": "mutual", "ranking": "auto", "manual": "admin"}
    return {
        "miniTournament": {
            "id": mt.id,
            "number": mt.number,
            "pairingDeadline": mt.pairing_deadline.isoformat() + "Z",
            "pairingClosed": mt.pairing_closed,
            "pairingOpen": not mt.pairing_closed and datetime.utcnow() <= mt.pairing_deadline,
        },
        "players": [
            {
                **serialize_player_short(p),
                "rankingPosition": p.ranking_position or 0,
                "paired": p.id in paired,
                # The viewer may not pick a partner they already played 3 mini-tournaments with.
                "allowedForMe": bool(in_roster and p.id != my_id and teams_pairing.allowed(my_id, p.id, history)),
            }
            for p in players
        ],
        "pairs": [
            {
                "id": pair.id,
                "source": source.get(pair.formed_by, pair.formed_by),
                "players": [serialize_player_short(Player.query.get(pid)) for pid in pair_players[pair.id]],
                "rankingPoints": sum((Player.query.get(pid).ranking_points or 0) for pid in pair_players[pair.id]),
            }
            for pair in pairs
        ],
        "me": {
            "playerId": my_id,
            "inRoster": in_roster,
            "myChoice": my_choice,
            "choseMe": chose_me,
            "pairId": next((pid for pid, ids in pair_players.items() if my_id in ids), None),
            "isAdmin": bool(viewer and viewer.is_admin),
        },
    }


def _current_or_404():
    mt = teams_pairing.current_mini_tournament()
    if mt is None:
        return None, (jsonify({"error": "Ainda não há mini-torneios da Teams."}), 404)
    return mt, None


@bp.route("/", methods=["GET"])
def get_state():
    mt, error = _current_or_404()
    if error:
        return error
    return jsonify(_state(mt, _viewer()))


def _run(action):
    """Run a pairing action and answer with the fresh state, or the rule it broke."""
    mt, error = _current_or_404()
    if error:
        return error
    user = jwt_user()
    try:
        action(mt, user)
    except PairingError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400
    return jsonify(_state(mt, user))


@bp.route("/partner", methods=["POST"])
@jwt_required()
def choose_partner():
    data = request.get_json() or {}
    try:
        partner_id = int(data.get("partnerId"))
    except (TypeError, ValueError):
        return jsonify({"error": "partnerId em falta."}), 400

    def action(mt, user):
        if user is None or user.player_id is None:
            raise PairingError("A tua conta não está associada a um jogador.")
        teams_pairing.declare(mt, user.player_id, partner_id)

    return _run(action)


@bp.route("/partner", methods=["DELETE"])
@jwt_required()
def withdraw_partner():
    def action(mt, user):
        if user is None or user.player_id is None:
            raise PairingError("A tua conta não está associada a um jogador.")
        teams_pairing.withdraw(mt, user.player_id)

    return _run(action)


@bp.route("/pairs", methods=["POST"])
@admin_required_jwt()
def admin_set_pair():
    ids = (request.get_json() or {}).get("playerIds") or []
    if len(ids) != 2:
        return jsonify({"error": "Indica dois jogadores."}), 400
    return _run(lambda mt, user: teams_pairing.set_pair(mt, int(ids[0]), int(ids[1])))


@bp.route("/pairs/<int:pair_id>", methods=["DELETE"])
@admin_required_jwt()
def admin_unpair(pair_id):
    return _run(lambda mt, user: teams_pairing.unpair(mt, pair_id))


@bp.route("/close_pairing", methods=["POST"])
@admin_required_jwt()
def admin_close_pairing():
    return _run(lambda mt, user: teams_pairing.close(mt))


@bp.route("/roster", methods=["PUT"])
@admin_required_jwt()
def admin_set_roster():
    ids = {int(i) for i in (request.get_json() or {}).get("playerIds") or []}
    known = {p.id for p in Player.query.filter(Player.id.in_(ids))}
    if ids != known:
        return jsonify({"error": f"Jogadores desconhecidos: {sorted(ids - known)}"}), 400
    return _run(lambda mt, user: teams_pairing.set_roster(mt, ids))


@bp.route("/roster/<int:player_id>", methods=["POST"])
@admin_required_jwt()
def admin_add_to_roster(player_id):
    return _run(lambda mt, user: teams_pairing.add_to_roster(mt, player_id))


@bp.route("/roster/<int:player_id>", methods=["DELETE"])
@admin_required_jwt()
def admin_remove_from_roster(player_id):
    return _run(lambda mt, user: teams_pairing.remove_from_roster(mt, player_id))
