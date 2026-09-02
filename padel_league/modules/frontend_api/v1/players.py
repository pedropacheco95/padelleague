import datetime
import os

import unidecode
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.model import Image
from padel_league.models import League, Player, User
from padel_league.tools import image_tools

from .serializers import (
    serialize_player_detail,
    serialize_player_ranking,
    serialize_player_short,
    serialize_user,
)

bp = Blueprint("api_v1_players", __name__, url_prefix="/api/v1/players")

PREFERED_HANDS = ("Direita", "Esquerda")
PREFERED_POSITIONS = ("Lado direito", "Lado esquerdo", "Tanto faz")


@bp.route("/ranking")
def ranking():
    league = League.query.first()
    players = league.players_rankings_position()
    return jsonify([serialize_player_ranking(p) for p in players])


@bp.route("/<int:id>")
def player(id):
    p = Player.query.filter_by(id=id).first_or_404()
    return jsonify(serialize_player_detail(p))


@bp.route("/all")
def players():
    ps = Player.query.all()
    return jsonify([serialize_player_detail(p) for p in ps])


@bp.route("/short/all")
def players_short():
    ps = Player.query.all()
    return jsonify([serialize_player_short(p) for p in ps])


def _save_player_picture(player, file):
    """Store an uploaded picture and point the player at it. Mirrors auth.register."""
    image_name = unidecode.unidecode(str(player.name).replace(" ", "").lower())
    filename = os.path.join("Player", f"{image_name}_{player.id}.png")
    if not image_tools.save_file(file, filename):
        return False
    img = Image(
        object_key=filename,
        content_type=getattr(file, "mimetype", None),
        is_public=True,
    )
    img.create()
    player.picture_id = img.id
    return True


@bp.route("/<int:id>", methods=["PUT"])
@jwt_required()
def update_player(id):
    """Update a player and its user account.

    A player may only edit itself; admins may edit anyone. Every field is
    optional — only the keys actually present in the form are touched, so a
    field that is currently empty can still be filled in.
    """
    player = Player.query.filter_by(id=id).first_or_404()

    current_user = User.query.get(get_jwt_identity())
    if not current_user:
        return jsonify({"error": "Utilizador não encontrado."}), 401
    if current_user.player_id != player.id and not current_user.is_admin:
        return jsonify({"error": "Só podes editar o teu próprio perfil."}), 403

    form = request.form
    user = player.user

    # ── Account fields ───────────────────────────────────────────────────────
    if user:
        username = (form.get("username") or "").strip()
        if username and username != user.username:
            if User.query.filter(
                User.username == username, User.id != user.id
            ).first():
                return (
                    jsonify({"error": f"O username {username} já está registado."}),
                    400,
                )
            user.username = username

        email = (form.get("email") or "").strip()
        if email and email != user.email:
            if User.query.filter(User.email == email, User.id != user.id).first():
                return jsonify({"error": f"O email {email} já está registado."}), 400
            user.email = email

        new_password = form.get("password") or ""
        if new_password:
            # Admins editing someone else don't know that person's password;
            # everyone changing their own has to prove they know it.
            if current_user.id == user.id:
                current_password = form.get("current_password") or ""
                if not current_password or not check_password_hash(
                    user.password, current_password
                ):
                    return jsonify({"error": "A password atual está errada."}), 400
            user.password = generate_password_hash(new_password)

        user.save()

    # ── Player fields ────────────────────────────────────────────────────────
    name = (form.get("name") or "").strip()
    if name and name != player.name:
        if Player.query.filter(Player.name == name, Player.id != player.id).first():
            return jsonify({"error": f"Já existe um jogador chamado {name}."}), 400
        player.name = name

    full_name = (form.get("full_name") or "").strip()
    if full_name and full_name != player.full_name:
        if Player.query.filter(
            Player.full_name == full_name, Player.id != player.id
        ).first():
            return (
                jsonify({"error": f"Já existe um jogador chamado {full_name}."}),
                400,
            )
        player.full_name = full_name

    prefered_hand = form.get("prefered_hand")
    if prefered_hand:
        if prefered_hand not in PREFERED_HANDS:
            return jsonify({"error": "Mão preferida inválida."}), 400
        player.prefered_hand = prefered_hand

    prefered_position = form.get("prefered_position")
    if prefered_position:
        if prefered_position not in PREFERED_POSITIONS:
            return jsonify({"error": "Posição preferida inválida."}), 400
        player.prefered_position = prefered_position

    height = form.get("height")
    if height:
        try:
            player.height = float(height)
        except ValueError:
            return jsonify({"error": "Altura inválida."}), 400

    birth_date = form.get("birth_date")
    if birth_date:
        try:
            player.birthday = datetime.datetime.strptime(birth_date, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "Data de nascimento inválida."}), 400

    for file in request.files.getlist("finalFile"):
        if file.filename:
            _save_player_picture(player, file)

    player.save()

    # The short form is enough for the caller to confirm the save; the user is
    # returned so the client can refresh its auth state after a username change.
    return jsonify(
        {
            "player": serialize_player_short(player),
            "user": serialize_user(user) if user else None,
        }
    )
