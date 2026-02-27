from flask import Blueprint, jsonify

from padel_league.models import League, Player

from .serializers import (
    serialize_player_detail,
    serialize_player_ranking,
    serialize_player_short,
)

bp = Blueprint("api_v1_players", __name__, url_prefix="/api/v1/players")


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
