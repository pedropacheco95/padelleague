from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from padel_league.domain.errors import Conflict, NotFound
from padel_league.services import shuffle
from padel_league.sql_db import db
from padel_league.tools.auth_tools import admin_required_jwt
from padel_league.models import (
    Association_PlayerMatch,
    Match,
    Player,
    ShuffleTournament,
)
from padel_league.modules.frontend_api.v1.player_comparison import (
    compute_head_to_head,
    compute_head_to_head_totals,
    compute_player_comparison_stats,
)
from padel_league.modules.frontend_api.v1.serializers import (
    _serialize_shuffle_player_relation,
    serialize_shuffle_tournament,
)

bp = Blueprint(
    "api_v1_shuffle_tournament", __name__, url_prefix="/api/v1/shuffle_tournament"
)


def _get_tournament_from_payload():
    data = request.get_json() or {}
    tournament_id = data.get("tournamentId")
    if tournament_id is None:
        return None, data, (jsonify({"error": "tournamentId is required"}), 400)

    try:
        tournament_id = int(tournament_id)
    except (TypeError, ValueError):
        return None, data, (jsonify({"error": "tournamentId must be an integer"}), 400)

    shuffle_tournament = ShuffleTournament.query.filter_by(
        id=tournament_id
    ).first_or_404()
    return shuffle_tournament, data, None


def _actor():
    from flask_jwt_extended import get_jwt_identity

    try:
        return int(get_jwt_identity())
    except (TypeError, ValueError, RuntimeError):
        return None


def _competition_id(shuffle_tournament):
    """compat.shuffle_tournaments.id = coalesce(legacy_shuffle_id, competitions.id)."""
    return shuffle.competition_for_tournament_id(shuffle_tournament.id).id


def _payload(shuffle_tournament_id):
    """The serialized tournament after a committed write. recalculate_player_stats
    sets stats on the compat (view) objects in memory; never flush them."""
    with db.session.no_autoflush:
        tournament = ShuffleTournament.query.filter_by(id=shuffle_tournament_id).first_or_404()
        tournament.recalculate_player_stats()
        payload = serialize_shuffle_tournament(tournament)
    db.session.rollback()
    return payload


@bp.route("", methods=["GET"])
@bp.route("/", methods=["GET"])
def detail():
    shuffle_tournament = (
        ShuffleTournament.query.filter_by(has_ended=False)
        .order_by(ShuffleTournament.id.desc())
        .first()
    )
    if not shuffle_tournament:
        shuffle_tournament = ShuffleTournament.query.order_by(
            ShuffleTournament.id.asc()
        ).first_or_404()

    shuffle_tournament.recalculate_player_stats()
    return jsonify(serialize_shuffle_tournament(shuffle_tournament))


@bp.route("/player_comparison", methods=["GET"])
def player_comparison():
    tournament_id = request.args.get("tournamentId", type=int)
    player1_id_raw = (request.args.get("player1Id") or "").strip()
    player2_id_raw = (request.args.get("player2Id") or "").strip()

    if not player1_id_raw or not player2_id_raw:
        return jsonify({"error": "player1Id and player2Id are required"}), 400
    if player1_id_raw == player2_id_raw:
        return jsonify({"error": "player1Id and player2Id must be different"}), 400

    if tournament_id is not None:
        shuffle_tournament = ShuffleTournament.query.filter_by(id=tournament_id).first()
    else:
        shuffle_tournament = (
            ShuffleTournament.query.filter_by(has_ended=False)
            .order_by(ShuffleTournament.id.desc())
            .first()
        )
        if not shuffle_tournament:
            shuffle_tournament = ShuffleTournament.query.order_by(
                ShuffleTournament.id.asc()
            ).first()

    if not shuffle_tournament:
        return jsonify({"error": "Shuffle tournament not found"}), 404

    shuffle_tournament.recalculate_player_stats()
    relation_by_player_id = {
        str(rel.player_id): rel for rel in shuffle_tournament.players_relations
    }

    if (
        player1_id_raw not in relation_by_player_id
        or player2_id_raw not in relation_by_player_id
    ):
        return jsonify({"error": "One or both players are not in this tournament"}), 400

    all_matches = list(shuffle_tournament.matches or [])
    played_matches = [
        m
        for m in all_matches
        if m.played and m.score1 is not None and m.score2 is not None
    ]
    matches_by_matchweek = {}
    for match in played_matches:
        matches_by_matchweek.setdefault(int(match.matchweek or 0), []).append(match)

    ranking_position_by_player_id = {
        str(rel.player_id): (rel.position or 9999)
        for rel in shuffle_tournament.players_relations
    }

    stats_1 = compute_player_comparison_stats(
        player_id=player1_id_raw,
        relation_by_player_id=relation_by_player_id,
        played_matches=played_matches,
        all_matches=all_matches,
        matches_by_matchweek=matches_by_matchweek,
        ranking_position_by_player_id=ranking_position_by_player_id,
        serialize_player_relation=_serialize_shuffle_player_relation,
        get_scores=lambda match, in_home: (
            int(match.score1 if in_home else match.score2),
            int(match.score2 if in_home else match.score1),
        ),
        get_division=lambda match: int(match.division or 0),
        get_multiplier=lambda match: int(
            shuffle_tournament.division_multipliers.get(int(match.division or 0), 1)
        ),
        get_relation_points=lambda rel: rel.points or 0,
    )
    stats_2 = compute_player_comparison_stats(
        player_id=player2_id_raw,
        relation_by_player_id=relation_by_player_id,
        played_matches=played_matches,
        all_matches=all_matches,
        matches_by_matchweek=matches_by_matchweek,
        ranking_position_by_player_id=ranking_position_by_player_id,
        serialize_player_relation=_serialize_shuffle_player_relation,
        get_scores=lambda match, in_home: (
            int(match.score1 if in_home else match.score2),
            int(match.score2 if in_home else match.score1),
        ),
        get_division=lambda match: int(match.division or 0),
        get_multiplier=lambda match: int(
            shuffle_tournament.division_multipliers.get(int(match.division or 0), 1)
        ),
        get_relation_points=lambda rel: rel.points or 0,
    )

    shuffle_h2h = compute_head_to_head(
        played_matches,
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

    league_h2h = []
    try:
        player1_id_int = int(player1_id_raw)
        player2_id_int = int(player2_id_raw)
        regular_matches = (
            Match.query.join(
                Association_PlayerMatch, Association_PlayerMatch.match_id == Match.id
            )
            .filter(
                Association_PlayerMatch.player_id.in_([player1_id_int, player2_id_int])
            )
            .filter(Match.played.is_(True))
            .filter(
                Match.games_home_team.isnot(None), Match.games_away_team.isnot(None)
            )
            .all()
        )
        regular_matches_by_id = {m.id: m for m in regular_matches}
        league_h2h = compute_head_to_head(
            list(regular_matches_by_id.values()),
            player1_id_raw,
            player2_id_raw,
            source="league",
            source_label="Liga",
            get_scores=lambda match, in_home: (
                int(match.games_home_team if in_home else match.games_away_team),
                int(match.games_away_team if in_home else match.games_home_team),
            ),
            get_division=lambda match: int(match.division_id or 0),
            get_division_label=lambda match: (
                match.division.name if match.division else None
            ),
        )
    except (TypeError, ValueError):
        league_h2h = []

    all_head_to_head = sorted(
        shuffle_h2h + league_h2h,
        key=lambda item: (
            int(item.get("matchweek") or 0),
            int(item.get("matchId") or 0),
        ),
        reverse=True,
    )

    head_to_head_totals = compute_head_to_head_totals(all_head_to_head)
    head_to_head = all_head_to_head[:5]

    return jsonify(
        {
            "tournamentId": shuffle_tournament.id,
            "totalPlayers": len(shuffle_tournament.players_relations or []),
            "player1": stats_1,
            "player2": stats_2,
            "headToHead": head_to_head,
            "headToHeadTotals": head_to_head_totals,
        }
    )


@bp.route("/remove_player_from_matchweek", methods=["POST"])
@jwt_required()
def remove_player_from_matchweek():
    data = request.get_json() or {}
    tournament_id = data.get("tournamentId")
    if tournament_id is None:
        return jsonify({"error": "tournamentId is required"}), 400

    try:
        tournament_id = int(tournament_id)
    except (TypeError, ValueError):
        return jsonify({"error": "tournamentId must be an integer"}), 400

    shuffle_tournament = ShuffleTournament.query.filter_by(
        id=tournament_id
    ).first_or_404()

    player_id = data.get("playerId")
    matchweek = data.get("matchweek")
    if player_id is None or matchweek is None:
        return jsonify({"error": "playerId and matchweek are required"}), 400

    try:
        player_id = int(player_id)
        matchweek = int(matchweek)
    except (TypeError, ValueError):
        return jsonify({"error": "playerId and matchweek must be integers"}), 400

    try:
        removed_count = shuffle.remove_player_from_round(
            _competition_id(shuffle_tournament), matchweek, player_id, actor_user_id=_actor()
        )
    except NotFound as exc:
        message = {
            "round_not_found": "No matches found for that matchweek",
            "player_not_in_round": "Player not found in that matchweek",
        }.get(exc.code, exc.message)
        return jsonify({"error": message}), 404
    db.session.commit()
    return jsonify({"removedAssociations": removed_count})


@bp.route("/calculate_divisions", methods=["POST"])
@admin_required_jwt(super_admin=True)
def calculate_divisions():
    shuffle_tournament, _, error_response = _get_tournament_from_payload()
    if error_response:
        return error_response

    shuffle.calculate_divisions(_competition_id(shuffle_tournament))
    db.session.commit()
    return jsonify(_payload(shuffle_tournament.id))


@bp.route("/undo_calculate_divisions", methods=["POST"])
@admin_required_jwt(super_admin=True)
def undo_calculate_divisions():
    shuffle_tournament, _, error_response = _get_tournament_from_payload()
    if error_response:
        return error_response

    shuffle.undo_calculate_divisions(_competition_id(shuffle_tournament))
    db.session.commit()
    return jsonify(_payload(shuffle_tournament.id))


@bp.route("/generate_matchweek", methods=["POST"])
@admin_required_jwt(super_admin=True)
def generate_matchweek():
    shuffle_tournament, _, error_response = _get_tournament_from_payload()
    if error_response:
        return error_response
    if not shuffle_tournament.players_relations:
        return jsonify({"error": "No players in tournament"}), 400

    try:
        shuffle.generate_round(_competition_id(shuffle_tournament), actor_user_id=_actor())
    except Conflict as exc:
        message = {
            "round_unfinished": "Cannot generate a new matchweek while there are unfinished matches.",
            "not_enough_players": "No divisions with enough players (minimum 8)",
            "competition_ended": "This shuffle tournament has ended.",
        }.get(exc.code, exc.message)
        return jsonify({"error": message}), 400
    db.session.commit()
    return jsonify(_payload(shuffle_tournament.id))


@bp.route("/delete_last_matchweek", methods=["POST"])
@admin_required_jwt(super_admin=True)
def delete_last_matchweek():
    shuffle_tournament, _, error_response = _get_tournament_from_payload()
    if error_response:
        return error_response

    if not shuffle_tournament.matches:
        return jsonify({"error": "No matchweeks found"}), 400
    last_matchweek = max(int(m.matchweek or 0) for m in shuffle_tournament.matches)
    deleted_matches = sum(1 for m in shuffle_tournament.matches if int(m.matchweek or 0) == last_matchweek)
    try:
        shuffle.delete_last_round(_competition_id(shuffle_tournament))
    except Conflict as exc:
        message = {
            "no_rounds": "No matchweeks found",
            "round_has_results": "Cannot delete the last matchweek because it already has played matches.",
        }.get(exc.code, exc.message)
        return jsonify({"error": message}), 400
    db.session.commit()
    return jsonify(
        {
            "deletedMatches": deleted_matches,
            "deletedMatchweek": last_matchweek,
            "tournament": _payload(shuffle_tournament.id),
        }
    )


@bp.route("/create", methods=["POST"])
@admin_required_jwt(super_admin=True)
def create():
    data = request.get_json() or {}
    required_fields = [
        "title",
        "max_players",
        "number_of_divisions",
        "has_ended",
        "division_multipliers",
        "players",
    ]
    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return (
            jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}),
            400,
        )

    try:
        title = str(data["title"]).strip()
        max_players = int(data["max_players"])
        number_of_divisions = int(data["number_of_divisions"])
        has_ended = bool(data["has_ended"])
        division_multipliers_raw = data["division_multipliers"] or {}
        players_payload = data["players"] or []
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid payload types"}), 400

    if not title:
        return jsonify({"error": "title is required"}), 400
    if max_players < 1:
        return jsonify({"error": "max_players must be >= 1"}), 400
    if number_of_divisions < 1:
        return jsonify({"error": "number_of_divisions must be >= 1"}), 400
    if not isinstance(division_multipliers_raw, dict):
        return jsonify({"error": "division_multipliers must be an object"}), 400
    if not isinstance(players_payload, list):
        return jsonify({"error": "players must be a list"}), 400
    if len(players_payload) > max_players:
        return jsonify({"error": "players list cannot exceed max_players"}), 400

    try:
        division_multipliers = {
            str(int(k)): int(v) for k, v in division_multipliers_raw.items()
        }
    except (TypeError, ValueError):
        return (
            jsonify(
                {"error": "division_multipliers must contain numeric keys and values"}
            ),
            400,
        )

    parsed_players = []
    seen_player_ids = set()
    seen_order_indexes = set()
    for item in players_payload:
        if not isinstance(item, dict):
            return jsonify({"error": "each players item must be an object"}), 400
        if "player_id" not in item or "order_index" not in item:
            return (
                jsonify(
                    {"error": "each players item requires player_id and order_index"}
                ),
                400,
            )
        try:
            player_id = int(item["player_id"])
            order_index = int(item["order_index"])
        except (TypeError, ValueError):
            return jsonify({"error": "player_id and order_index must be integers"}), 400

        if order_index < 1:
            return jsonify({"error": "order_index must be >= 1"}), 400
        if player_id in seen_player_ids:
            return jsonify({"error": f"duplicate player_id: {player_id}"}), 400
        if order_index in seen_order_indexes:
            return jsonify({"error": f"duplicate order_index: {order_index}"}), 400

        seen_player_ids.add(player_id)
        seen_order_indexes.add(order_index)
        parsed_players.append({"player_id": player_id, "order_index": order_index})

    existing_players = (
        Player.query.filter(Player.id.in_(seen_player_ids)).all()
        if seen_player_ids
        else []
    )
    existing_player_ids = {p.id for p in existing_players}
    missing_player_ids = sorted(seen_player_ids - existing_player_ids)
    if missing_player_ids:
        return jsonify({"error": f"player(s) not found: {missing_player_ids}"}), 400

    competition = shuffle.create_shuffle(
        title,
        [(item["player_id"], item["order_index"]) for item in parsed_players],
        number_of_divisions=number_of_divisions,
        max_players=max_players,
        multipliers_by_tier={int(k): v for k, v in division_multipliers.items()},
        has_ended=has_ended,
    )
    db.session.commit()
    return jsonify(_payload(competition.legacy_shuffle_id or competition.id)), 201
