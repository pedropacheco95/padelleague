import datetime
import os

import unidecode
from flask import Blueprint, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt_identity,
    jwt_required,
)
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.model import Image
from padel_league.models import Player, User
from padel_league.tools import image_tools
from padel_league.tools.rate_limit import code_requests

bp = Blueprint("api_v1_auth", __name__, url_prefix="/api/v1/auth")


def _tokens(user, password_reset=False):
    """A short-lived access token plus the refresh token the site renews it with.

    password_reset marks the access token issued after the emailed code, which
    may set a new password without the current one.
    """
    identity = str(user.id)
    claims = {"password_reset": True} if password_reset else None
    return {
        "access_token": create_access_token(identity=identity, additional_claims=claims),
        "refresh_token": create_refresh_token(identity=identity),
    }


@bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    user = User.query.filter_by(username=username).first()

    if user is None:
        return jsonify({"error": "Enganaste-te no username oh burro."}), 401
    if not check_password_hash(user.password, password):
        return jsonify({"error": "Enganaste-te na password oh burro."}), 401

    return jsonify({"user": user.serialize(), **_tokens(user)})


@bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    """Swap a valid refresh token for a new pair, so an active player never expires."""
    user = User.query.get(int(get_jwt_identity()))
    if user is None:
        return jsonify({"error": "User not found"}), 401
    return jsonify(_tokens(user))


@bp.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    return jsonify({"message": "Logged out"})


@bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"user": user.serialize()})


# Anyone can ask for a code for any account (that is what forgot-password is), so
# requests are rate limited per client IP and per account. The counters are
# in-process (tools/rate_limit.py): per gunicorn worker, reset on restart.
CODE_REQUESTS_PER_IP = 20
CODE_REQUESTS_PER_ACCOUNT = 5
CODE_REQUESTS_WINDOW_SECONDS = 15 * 60
TOO_MANY_CODE_REQUESTS = {"error": "Demasiados pedidos de código. Tenta mais tarde."}


def _client_ip():
    # Behind the host nginx every request arrives from 127.0.0.1; the first
    # X-Forwarded-For hop is the client. Spoofable, hence the per-account limit too.
    forwarded = request.headers.get("X-Forwarded-For", "")
    return (forwarded.split(",")[0].strip() if forwarded else None) or request.remote_addr or "?"


def _code_request_allowed(account_key):
    if not code_requests.allow(("ip", _client_ip()), CODE_REQUESTS_PER_IP, CODE_REQUESTS_WINDOW_SECONDS):
        return False
    return code_requests.allow(("account", account_key), CODE_REQUESTS_PER_ACCOUNT, CODE_REQUESTS_WINDOW_SECONDS)


def _request_code(user):
    """Keep the pending code, or make one. The emails on file are mostly fake, so the code is
    not emailed: an admin sends it by WhatsApp from /admin/passwords (api/v2/admin/password-codes).
    Asking again never replaces a code an admin may already have sent."""
    if user.generated_code is None:
        user.new_code()
        user.save()


@bp.route("/forgot_password", methods=["POST"])
def forgot_password():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()

    if not _code_request_allowed(username.lower()):
        return jsonify(TOO_MANY_CODE_REQUESTS), 429
    user = User.query.filter_by(username=username).first() if username else None
    if user is None:
        return jsonify({"error": "Enganaste-te no username oh burro."}), 404

    _request_code(user)
    return jsonify({"user_id": user.id})


@bp.route("/verify_generated_code/<int:user_id>", methods=["POST"])
def verify_generated_code(user_id):
    data = request.get_json()
    generated_code = data.get("generated_code")

    user = User.query.filter_by(id=user_id).first()
    if not user:
        return jsonify({"error": "Utilizador não encontrado."}), 404
    try:
        code = int(generated_code)
    except (TypeError, ValueError):
        code = None
    if not user.use_code(code):
        user.save()
        if user.generated_code is None:
            return jsonify({"error": "Código expirado ou demasiadas tentativas. Pede um código novo."}), 400
        return jsonify({"error": "Código errado."}), 400
    user.save()

    return jsonify({"player_id": user.player_id, "user": user.serialize(), **_tokens(user, password_reset=True)})


@bp.route("/generate_new_code/<int:user_id>", methods=["POST"])
def generate_new_code(user_id):
    """Same as forgot_password (no email; a pending code is kept)."""
    if not _code_request_allowed(user_id):
        return jsonify(TOO_MANY_CODE_REQUESTS), 429
    user = User.query.filter_by(id=user_id).first()
    if not user:
        return jsonify({"error": "Utilizador não encontrado."}), 404
    _request_code(user)
    return jsonify({"message": "Pedido enviado."})


@bp.route("/register", methods=["POST"])
def register():
    username = request.form.get("username")
    email = request.form.get("email")
    password = generate_password_hash(request.form.get("password", ""))
    name = request.form.get("name")
    full_name = request.form.get("full_name")
    prefered_hand = request.form.get("prefered_hand")
    prefered_position = request.form.get("prefered_position")
    height = request.form.get("height")
    birth_date = request.form.get("birth_date")
    birthday = (
        datetime.datetime.strptime(birth_date, "%Y-%m-%d") if birth_date else None
    )
    final_files = request.files.getlist("finalFile")

    if not username:
        return jsonify({"error": "Tens que por um username oh burro."}), 400
    if not password:
        return jsonify({"error": "Tens que por uma password oh burro."}), 400
    if User.query.filter_by(username=username).first():
        return (
            jsonify({"error": f"O username {username} já está registado oh burro."}),
            400,
        )
    if User.query.filter_by(email=email).first():
        return jsonify({"error": f"O email {email} já está registado oh burro."}), 400
    if not name:
        return jsonify({"error": "Tens que por um nome oh burro."}), 400

    player = Player(name=name)
    player.create()
    if full_name:
        player.full_name = full_name
    if birthday:
        player.birthday = birthday
    if height:
        player.height = height
    if prefered_hand:
        player.prefered_hand = prefered_hand
    if prefered_position:
        player.prefered_position = prefered_position
    player.save()

    for file in final_files:
        if file.filename != "":
            image_name = unidecode.unidecode(str(player.name).replace(" ", "").lower())
            image_name = f"{image_name}_{player.id}.png"
            filename = os.path.join("Player", image_name)
            if image_tools.save_file(file, filename):
                img = Image(
                    object_key=filename,
                    content_type=getattr(file, "mimetype", None),
                    is_public=True,
                )
                img.create()
                player.picture_id = img.id
            player.save()

    user = User(username=username, email=email, password=password, player_id=player.id)
    user.create()

    return jsonify({"user": user.serialize(), **_tokens(user)}), 201
