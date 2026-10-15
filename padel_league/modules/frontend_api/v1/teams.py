from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, verify_jwt_in_request

from padel_league.models import Player
from padel_league.models.teams import TeamsPair, TeamsPartnerRequest, TeamsPlayer
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
    roster = TeamsPlayer.query.all()
    players = sorted((row.player for row in roster), key=teams_pairing.ranking_key)
    pairs = TeamsPair.query.filter_by(mini_tournament_id=mt.id).order_by(TeamsPair.id).all()
    paired = {pid for p in pairs for pid in p.player_ids}
    my_id = viewer.player_id if viewer else None
    in_roster = my_id in {p.id for p in players}

    my_choice, chose_me = None, []
    if in_roster:
        mine = TeamsPartnerRequest.query.filter_by(mini_tournament_id=mt.id, player_id=my_id).first()
        my_choice = mine.partner_id if mine else None
        chose_me = [
            r.player_id
            for r in TeamsPartnerRequest.query.filter_by(mini_tournament_id=mt.id, partner_id=my_id)
            if r.player_id not in paired
        ]

    history = teams_pairing.times_together(mt.id)
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
                "source": pair.source,
                "players": [serialize_player_short(pair.player_a), serialize_player_short(pair.player_b)],
                "rankingPoints": (pair.player_a.ranking_points or 0) + (pair.player_b.ranking_points or 0),
            }
            for pair in pairs
        ],
        "me": {
            "playerId": my_id,
            "inRoster": in_roster,
            "myChoice": my_choice,
            "choseMe": chose_me,
            "pairId": next((p.id for p in pairs if my_id in p.player_ids), None),
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
    TeamsPlayer.query.filter(~TeamsPlayer.player_id.in_(ids)).delete(synchronize_session=False)
    present = {row.player_id for row in TeamsPlayer.query.all()}
    db.session.add_all(TeamsPlayer(player_id=i) for i in ids - present)
    db.session.commit()
    mt, error = _current_or_404()
    return error or jsonify(_state(mt, jwt_user()))


@bp.route("/roster/<int:player_id>", methods=["POST"])
@admin_required_jwt()
def admin_add_to_roster(player_id):
    def action(mt, user):
        if db.session.get(Player, player_id) is None:
            raise PairingError("Jogador desconhecido.")
        if db.session.get(TeamsPlayer, player_id) is None:
            db.session.add(TeamsPlayer(player_id=player_id))
            db.session.commit()

    return _run(action)


@bp.route("/roster/<int:player_id>", methods=["DELETE"])
@admin_required_jwt()
def admin_remove_from_roster(player_id):
    def action(mt, user):
        if teams_pairing.pair_of(mt.id, player_id):
            raise PairingError("Desfaz primeiro a parelha deste jogador.")
        TeamsPartnerRequest.query.filter(
            TeamsPartnerRequest.mini_tournament_id == mt.id,
            (TeamsPartnerRequest.player_id == player_id) | (TeamsPartnerRequest.partner_id == player_id),
        ).delete(synchronize_session=False)
        TeamsPlayer.query.filter_by(player_id=player_id).delete()
        db.session.commit()

    return _run(action)
