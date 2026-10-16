import datetime
import os

import unidecode
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league.model import Image
from padel_league.models import League, Player, User
from padel_league.models.v2 import MatchParticipant
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

# Outside substitutes (players.status = 'external', SUBS_ import) stay out of the
# lists and the ranking; their profile is still reachable by id.
NOT_EXTERNAL = text("players.status <> 'external'")


def _seats(player_ids):
    """{player id: ({member match ids}, {substitute match ids})} from match_participants."""
    out = {pid: (set(), set()) for pid in player_ids}
    rows = MatchParticipant.query.filter(MatchParticipant.player_id.in_(player_ids)).with_entities(
        MatchParticipant.player_id, MatchParticipant.match_id, MatchParticipant.role
    )
    for pid, match_id, role in rows:
        out[pid][0 if role == "member" else 1].add(match_id)
    return out


def player_detail(player, seats):
    """serialize_player_detail with the stats counting the player's own (member) seats only.

    compat.players_in_match lists every occupant, so after the SUBS_ import a sub
    appearance would add to matches, wins and attendance (107%). It is counted
    apart, in subsMatches."""
    data = serialize_player_detail(player)
    member_ids, sub_ids = seats
    played = [r for r in player.matches_relations if r.match.played]
    mine = [r for r in played if r.match_id in member_ids]

    def counts(rels):
        won = sum((r.team == "Home" and r.match.winner == 1) or (r.team == "Away" and r.match.winner == -1) for r in rels)
        lost = sum((r.team == "Home" and r.match.winner == -1) or (r.team == "Away" and r.match.winner == 1) for r in rels)
        drawn = sum(r.match.winner == 0 for r in rels)
        return won, lost, drawn

    n_played = len(mine)
    n_won, n_lost, n_drawn = counts(mine)
    n_tournaments = data["tournamentsPlayed"]
    data.update(
        {
            "matchesPlayed": n_played,
            "matchesWon": n_won,
            "matchesLost": n_lost,
            "matchesDrawn": n_drawn,
            "efficiency": round(n_won / n_played * 100, 2) if n_played else 0,
            "matchweeksPlayed": round(n_played / 3) if n_played else 0,
            "matchweeksMissed": (
                round(n_tournaments * 7 - n_played / 3) if n_played and n_tournaments else 0
            ),
            "matchweeksPerTournament": (
                round(n_played / 3 / n_tournaments, 2) if n_played and n_tournaments else 0
            ),
            "attendance": (
                round(n_played / (n_tournaments * 3 * 7) * 100, 2) if n_played and n_tournaments else 0
            ),
            "subsMatches": sum(r.match_id in sub_ids for r in played),
        }
    )
    for row in data["tournamentHistory"]:
        in_division = [r for r in mine if r.match.division_id == row["divisionId"]]
        row["played"] = len(in_division)
        row["won"] = counts(in_division)[0]
    return data


@bp.route("/ranking")
def ranking():
    league = League.query.first()
    players = league.players_rankings_position()
    hidden = {
        pid
        for pid, in Player.query.filter(
            Player.id.in_([p.id for p in players]), text("players.status = 'external'")
        ).with_entities(Player.id)
    }
    return jsonify([serialize_player_ranking(p) for p in players if p.id not in hidden])


@bp.route("/<int:id>")
def player(id):
    p = Player.query.filter_by(id=id).first_or_404()
    return jsonify(player_detail(p, _seats([p.id])[p.id]))


@bp.route("/all")
def players():
    ps = Player.query.filter(NOT_EXTERNAL).all()
    seats = _seats([p.id for p in ps])
    return jsonify([player_detail(p, seats[p.id]) for p in ps])


@bp.route("/short/all")
def players_short():
    ps = Player.query.filter(NOT_EXTERNAL).all()
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
            # everyone changing their own has to prove they know it, unless they
            # just proved who they are with the emailed code (forgot password).
            if current_user.id == user.id and not get_jwt().get("password_reset"):
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
