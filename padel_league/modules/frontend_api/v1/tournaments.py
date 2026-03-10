from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from padel_league.models import (
    Association_PlayerMatch,
    Association_PlayerShuffleMatch,
    Division,
    ShuffleMatch,
)
from padel_league.modules.frontend_api.v1.player_comparison import (
    compute_head_to_head,
    compute_head_to_head_totals,
    compute_player_comparison_stats,
)
from padel_league.modules.frontend_api.v1.serializers import (
    _serialize_division_player_relation,
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


@bp.route("/<int:id>/player_comparison", methods=["GET"])
def player_comparison(id):
    division = Division.query.filter_by(id=id).first_or_404()
    player1_id_raw = (request.args.get("player1Id") or "").strip()
    player2_id_raw = (request.args.get("player2Id") or "").strip()

    if not player1_id_raw or not player2_id_raw:
        return jsonify({"error": "player1Id and player2Id are required"}), 400
    if player1_id_raw == player2_id_raw:
        return jsonify({"error": "player1Id and player2Id must be different"}), 400

    try:
        division.update_table(False)
    except Exception:
        pass

    relation_by_player_id = {
        str(rel.player_id): rel for rel in division.players_relations
    }
    if (
        player1_id_raw not in relation_by_player_id
        or player2_id_raw not in relation_by_player_id
    ):
        return jsonify({"error": "One or both players are not in this tournament"}), 400

    all_matches = list(division.matches or [])
    played_matches = [
        m
        for m in all_matches
        if m.played and m.games_home_team is not None and m.games_away_team is not None
    ]
    matches_by_matchweek = {}
    for match in played_matches:
        matches_by_matchweek.setdefault(int(match.matchweek or 0), []).append(match)

    standings_relations = list(division.players_relations_classification())
    ranking_position_by_player_id = {
        str(rel.player_id): (index + 1) for index, rel in enumerate(standings_relations)
    }

    stats_1 = compute_player_comparison_stats(
        player_id=player1_id_raw,
        relation_by_player_id=relation_by_player_id,
        played_matches=played_matches,
        all_matches=all_matches,
        matches_by_matchweek=matches_by_matchweek,
        ranking_position_by_player_id=ranking_position_by_player_id,
        serialize_player_relation=_serialize_division_player_relation,
        get_scores=lambda match, in_home: (
            int(match.games_home_team if in_home else match.games_away_team),
            int(match.games_away_team if in_home else match.games_home_team),
        ),
        get_division=lambda _match: int(division.id),
        get_multiplier=lambda _match: 1,
        get_relation_points=lambda rel: (
            round(rel.points) if rel.points is not None else 0
        ),
    )
    stats_2 = compute_player_comparison_stats(
        player_id=player2_id_raw,
        relation_by_player_id=relation_by_player_id,
        played_matches=played_matches,
        all_matches=all_matches,
        matches_by_matchweek=matches_by_matchweek,
        ranking_position_by_player_id=ranking_position_by_player_id,
        serialize_player_relation=_serialize_division_player_relation,
        get_scores=lambda match, in_home: (
            int(match.games_home_team if in_home else match.games_away_team),
            int(match.games_away_team if in_home else match.games_home_team),
        ),
        get_division=lambda _match: int(division.id),
        get_multiplier=lambda _match: 1,
        get_relation_points=lambda rel: (
            round(rel.points) if rel.points is not None else 0
        ),
    )

    league_h2h = compute_head_to_head(
        played_matches,
        player1_id_raw,
        player2_id_raw,
        source="league",
        source_label="Liga",
        get_scores=lambda match, in_home: (
            int(match.games_home_team if in_home else match.games_away_team),
            int(match.games_away_team if in_home else match.games_home_team),
        ),
        get_division=lambda match: int(match.division_id or division.id),
        get_division_label=lambda _match: division.name,
    )

    shuffle_h2h = []
    try:
        player1_id_int = int(player1_id_raw)
        player2_id_int = int(player2_id_raw)
        shuffle_matches = (
            ShuffleMatch.query.join(
                Association_PlayerShuffleMatch,
                Association_PlayerShuffleMatch.shuffle_match_id == ShuffleMatch.id,
            )
            .filter(
                Association_PlayerShuffleMatch.player_id.in_(
                    [player1_id_int, player2_id_int]
                )
            )
            .filter(ShuffleMatch.played.is_(True))
            .filter(ShuffleMatch.score1.isnot(None), ShuffleMatch.score2.isnot(None))
            .all()
        )
        shuffle_matches_by_id = {m.id: m for m in shuffle_matches}
        shuffle_h2h = compute_head_to_head(
            list(shuffle_matches_by_id.values()),
            player1_id_raw,
            player2_id_raw,
            source="shuffle",
            source_label="Shuffle",
            get_scores=lambda match, in_home: (
                int(match.score1 if in_home else match.score2),
                int(match.score2 if in_home else match.score1),
            ),
            get_division=lambda match: int(match.division or 0),
        )
    except (TypeError, ValueError):
        shuffle_h2h = []

    all_head_to_head = sorted(
        league_h2h + shuffle_h2h,
        key=lambda item: (
            int(item.get("matchweek") or 0),
            int(item.get("matchId") or 0),
        ),
        reverse=True,
    )

    return jsonify(
        {
            "tournamentId": division.id,
            "totalPlayers": len(division.players_relations or []),
            "player1": stats_1,
            "player2": stats_2,
            "headToHead": all_head_to_head[:5],
            "headToHeadTotals": compute_head_to_head_totals(all_head_to_head),
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
