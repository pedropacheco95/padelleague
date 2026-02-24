import datetime
import os
import random

import unidecode
from flask import Blueprint, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    get_jwt_identity,
    jwt_required,
)
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.model import Image
from padel_league.models import Player, User
from padel_league.tools import email_tools, image_tools

bp = Blueprint("api_v1_auth", __name__, url_prefix="/api/v1/auth")


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

    access_token = create_access_token(identity=str(user.id))
    return jsonify({"user": user.serialize(), "access_token": access_token})


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


@bp.route("/forgot_password", methods=["POST"])
def forgot_password():
    data = request.get_json()
    username = data.get("username")

    user = User.query.filter_by(username=username).first()
    if user is None:
        return jsonify({"error": "Enganaste-te no username oh burro."}), 404

    generated_code = random.randint(10000, 99999)
    user.generated_code = generated_code
    user.save()

    mail_body = f"O teu código de autenticação é: {generated_code}"
    email_tools.send_email("Código autenticação", [user.email], html=mail_body)

    return jsonify({"user_id": user.id})


@bp.route("/verify_generated_code/<int:user_id>", methods=["POST"])
def verify_generated_code(user_id):
    data = request.get_json()
    generated_code = data.get("generated_code")

    user = User.query.filter_by(id=user_id).first()
    if not user:
        return jsonify({"error": "Utilizador não encontrado."}), 404
    if int(generated_code) != user.generated_code:
        return jsonify({"error": "Código errado."}), 400

    user.generated_code = None
    user.save()

    access_token = create_access_token(identity=str(user.id))
    return jsonify({"player_id": user.player_id, "access_token": access_token})


@bp.route("/generate_new_code/<int:user_id>", methods=["POST"])
def generate_new_code(user_id):
    user = User.query.filter_by(id=user_id).first()
    if not user:
        return jsonify({"error": "Utilizador não encontrado."}), 404

    generated_code = random.randint(10000, 99999)
    user.generated_code = generated_code
    user.save()

    mail_body = f"O teu novo código de autenticação é: {generated_code}"
    email_tools.send_email("Código autenticação", [user.email], html=mail_body)

    return jsonify({"message": "Novo código enviado."})


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

    access_token = create_access_token(identity=str(user.id))
    return jsonify({"user": user.serialize(), "access_token": access_token}), 201
