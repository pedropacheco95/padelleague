from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from padel_league.models import Association_PlayerMatch, Division
from padel_league.modules.frontend_api.v1.serializers import (
    serialize_division,
    serialize_match,
    serialize_player,
    serialize_standings_row,
)

bp = Blueprint("api_v1_tournaments", __name__, url_prefix="/api/v1/tournaments")


@bp.route("/", methods=["GET"])
def tournaments():
    active = Division.query.filter_by(has_ended=False).order_by(Division.id.asc()).all()
    ended = Division.query.filter_by(has_ended=True).order_by(Division.id.desc()).all()
    return jsonify(
        {
            "active": [serialize_division(d, short=True) for d in active],
            "ended": [serialize_division(d, short=True) for d in ended],
        }
    )


@bp.route("/<int:id>", methods=["GET"])
def tournament(id):
    division = Division.query.filter_by(id=id).first_or_404()

    try:
        division.update_table(False)
    except Exception:
        pass

    standings = [
        serialize_standings_row(rel, position)
        for position, rel in enumerate(
            division.players_relations_classification(), start=1
        )
    ]

    players = [
        serialize_player(rel.player, short=True) for rel in division.players_relations
    ]

    return jsonify(
        {
            "division": {
                **serialize_division(division),
                "tournamentName": division.tournament_name(),
            },
            "standings": standings,
            "matches": [
                serialize_match(m) for m in division.get_ordered_matches_played()
            ],
            "allMatches": [serialize_match(m) for m in division.get_ordered_matches()],
            "players": players,
        }
    )


@bp.route("/<int:id>/remove_player_from_matchweek", methods=["POST"])
@jwt_required()
def remove_player_from_matchweek(id):
    division = Division.query.filter_by(id=id).first_or_404()
    data = request.get_json() or {}

    player_id = data.get("playerId")
    matchweek = data.get("matchweek")
    if player_id is None or matchweek is None:
        return jsonify({"error": "playerId and matchweek are required"}), 400

    try:
        player_id = int(player_id)
        matchweek = int(matchweek)
    except (TypeError, ValueError):
        return jsonify({"error": "playerId and matchweek must be integers"}), 400

    removed_count = 0
    for match in division.matches:
        if match.matchweek != matchweek:
            continue

        assoc = Association_PlayerMatch.query.filter_by(
            match_id=match.id, player_id=player_id
        ).first()
        if assoc:
            assoc.delete()
            removed_count += 1

    return jsonify({"removedAssociations": removed_count})
