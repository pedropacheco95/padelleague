"""Login, token renewal and the signed-in user. Tokens stay snake_case (spec `Tokens`)."""

from flask import Blueprint, jsonify
from flask_jwt_extended import create_access_token, create_refresh_token, get_jwt_identity, verify_jwt_in_request
from flask_jwt_extended.exceptions import JWTExtendedException
from jwt.exceptions import PyJWTError
from werkzeug.security import check_password_hash

from padel_league.models import User

from . import serializers as ser
from ._http import ApiError, json_body, register_error_handlers, require_user, role_required

bp = Blueprint("api_v2_auth", __name__, url_prefix="/api/v2/auth")
register_error_handlers(bp)


def tokens(user):
    identity = str(user.id)
    return {
        "access_token": create_access_token(identity=identity),
        "refresh_token": create_refresh_token(identity=identity),
    }


@bp.route("/login", methods=["POST"])
def login():
    data = json_body()
    username, password = data.get("username"), data.get("password")
    user = User.query.filter_by(username=username).first() if username else None
    if user is None or not password or not check_password_hash(user.password, password):
        raise ApiError(401, "Username ou password errados.", "invalid_credentials")
    return jsonify({**tokens(user), "user": ser.user(user)})


@bp.route("/refresh", methods=["POST"])
def refresh():
    try:
        verify_jwt_in_request(refresh=True)
    except (JWTExtendedException, PyJWTError):
        raise ApiError(401, "Sessão expirada. Entra outra vez.", "unauthorized")
    user = User.query.get(int(get_jwt_identity()))
    if user is None:
        raise ApiError(401, "Utilizador não encontrado.", "unauthorized")
    return jsonify(tokens(user))


@bp.route("/me", methods=["GET"])
@role_required("player")
def me():
    return jsonify({"user": ser.user(require_user())})
