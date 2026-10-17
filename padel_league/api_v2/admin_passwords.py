"""Password codes for players who forgot theirs. The emails on file are mostly fake, so admins
send the code by WhatsApp: a player's request (v1 /auth/forgot_password) leaves a pending code on
their user, listed here; an admin can also make one for any player. The player types it at
/verify-code/<userId> (v1 verify_generated_code) and sets a new password."""

from flask import Blueprint, jsonify

from padel_league.models import Player, User

from . import serializers as ser
from ._http import int_arg, json_body, not_found, register_error_handlers, role_required

bp = Blueprint("api_v2_admin_passwords", __name__, url_prefix="/api/v2/admin")
register_error_handlers(bp)


def _code(user):
    return {
        "userId": user.id,
        "username": user.username,
        "player": ser.player_ref(user.player),
        "code": f"{int(user.generated_code):05d}",  # the column is a float in the live schema
    }


@bp.route("/password-codes", methods=["GET"])
@role_required("admin")
def list_codes():
    users = User.query.filter(User.generated_code.isnot(None)).order_by(User.username).all()
    return jsonify([_code(u) for u in users])


@bp.route("/password-codes", methods=["POST"])
@role_required("admin")
def make_code():
    player_id = int_arg(json_body().get("playerId"), "playerId", required=True)
    player = Player.query.get(player_id)
    if player is None:
        raise not_found("Jogador não encontrado.", "player_not_found")
    user = User.query.filter_by(player_id=player.id).first()
    if user is None:
        raise not_found("Este jogador não tem conta no site.", "user_not_found")
    if user.generated_code is None:
        user.new_code()
        user.save()
    return jsonify(_code(user))


@bp.route("/password-codes/<int:user_id>", methods=["DELETE"])
@role_required("admin")
def dismiss_code(user_id):
    user = User.query.get(user_id)
    if user is None:
        raise not_found("Utilizador não encontrado.", "user_not_found")
    user.generated_code = None
    user.code_attempts = 0
    user.save()
    return "", 204
