from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from padel_league.models import (
    Association_PlayerShuffleMatch,
    Association_PlayerShuffleTournament,
    Player,
    ShuffleMatch,
    ShuffleTournament,
)
from padel_league.modules.frontend_api.v1.serializers import (
    serialize_shuffle_tournament,
    _serialize_shuffle_player_relation,
)

bp = Blueprint(
    "api_v1_shuffle_tournament", __name__, url_prefix="/api/v1/shuffle_tournament"
)


def _compute_player_comparison_stats(
    tournament,
    player_id,
    relation_by_player_id,
    played_matches,
    all_matches,
    matches_by_matchweek,
    ranking_position_by_player_id,
):
    results = []
    divisions_played = set()
    normalized_player_id = str(player_id)

    for match in played_matches:
        home_ids = [
            str(rel.player_id) for rel in match.players_relations if rel.team == "Home"
        ]
        away_ids = [
            str(rel.player_id) for rel in match.players_relations if rel.team == "Away"
        ]
        in_home = normalized_player_id in home_ids
        in_away = normalized_player_id in away_ids

        if not in_home and not in_away:
            continue

        divisions_played.add(int(match.division or 0))
        team_ids = home_ids if in_home else away_ids
        opp_ids = away_ids if in_home else home_ids

        partner_candidates = [pid for pid in team_ids if pid != normalized_player_id]
        partner_id = partner_candidates[0] if partner_candidates else "sub"
        opponent_1 = opp_ids[0] if len(opp_ids) > 0 else "sub"
        opponent_2 = opp_ids[1] if len(opp_ids) > 1 else "sub"

        team_score = int(match.score1 if in_home else match.score2)
        opp_score = int(match.score2 if in_home else match.score1)

        results.append(
            {
                "matchweek": int(match.matchweek or 0),
                "division": int(match.division or 0),
                "partnerId": partner_id,
                "opponentIds": [opponent_1, opponent_2],
                "teamScore": team_score,
                "oppScore": opp_score,
                "won": team_score > opp_score,
                "drew": team_score == opp_score,
            }
        )

    wins = len([r for r in results if r["won"]])
    draws = len([r for r in results if r["drew"]])
    losses = len(results) - wins - draws
    win_rate = round((wins / len(results)) * 100) if results else 0
    divisions_sorted = sorted(divisions_played)

    current_streak = {"type": "W", "count": 0}
    ordered_results = sorted(
        results,
        key=lambda r: (r["matchweek"], r["teamScore"], r["oppScore"]),
        reverse=True,
    )
    if ordered_results:
        first = ordered_results[0]
        streak_type = "W" if first["won"] else ("D" if first["drew"] else "L")
        streak_count = 1
        for r in ordered_results[1:]:
            item_type = "W" if r["won"] else ("D" if r["drew"] else "L")
            if item_type == streak_type:
                streak_count += 1
            else:
                break
        current_streak = {"type": streak_type, "count": streak_count}

    best_win_diff = 0
    for r in results:
        if r["won"]:
            best_win_diff = max(best_win_diff, r["teamScore"] - r["oppScore"])

    worst_loss_diff = 0
    for r in results:
        if (not r["won"]) and (not r["drew"]):
            worst_loss_diff = max(worst_loss_diff, r["oppScore"] - r["teamScore"])

    def avg_opponent_position(result):
        opp1 = result["opponentIds"][0] if result["opponentIds"][0] != "sub" else "sub"
        opp2 = result["opponentIds"][1] if result["opponentIds"][1] != "sub" else "sub"
        return (
            ranking_position_by_player_id.get(opp1, 9999)
            + ranking_position_by_player_id.get(opp2, 9999)
        ) / 2

    biggest_wins = sorted(
        [r for r in results if r["won"]],
        key=avg_opponent_position,
    )[:3]
    worst_losses = sorted(
        [r for r in results if (not r["won"]) and (not r["drew"])],
        key=avg_opponent_position,
        reverse=True,
    )[:3]

    max_matchweek = max([int(m.matchweek or 0) for m in all_matches], default=0)
    all_player_ids = list(relation_by_player_id.keys())
    cumulative_points = {}

    for pid in all_player_ids:
        points_by_mw = {}
        running_points = 0
        for mw in range(1, max_matchweek + 1):
            for match in matches_by_matchweek.get(mw, []):
                home_ids = [
                    rel.player_id
                    for rel in match.players_relations
                    if rel.team == "Home"
                ]
                away_ids = [
                    rel.player_id
                    for rel in match.players_relations
                    if rel.team == "Away"
                ]
                home_ids = [str(pid) for pid in home_ids]
                away_ids = [str(pid) for pid in away_ids]
                in_home = pid in home_ids
                in_away = pid in away_ids
                if not in_home and not in_away:
                    continue

                team_score = int(match.score1 if in_home else match.score2)
                opp_score = int(match.score2 if in_home else match.score1)
                multiplier = int(
                    tournament.division_multipliers.get(int(match.division or 0), 1)
                )
                if team_score > opp_score:
                    running_points += 3 * multiplier
                elif team_score == opp_score:
                    running_points += 1 * multiplier
            points_by_mw[mw] = running_points
        cumulative_points[pid] = points_by_mw

    snapshots = []
    for mw in range(1, max_matchweek + 1):
        rankings = sorted(
            all_player_ids,
            key=lambda pid: (
                -(cumulative_points.get(pid, {}).get(mw, 0)),
                ranking_position_by_player_id.get(pid, 9999),
                pid,
            ),
        )
        snapshots.append(
            {
                "matchweek": mw,
                "points": cumulative_points.get(normalized_player_id, {}).get(mw, 0),
                "position": (
                    rankings.index(normalized_player_id) + 1
                    if normalized_player_id in rankings
                    else 0
                ),
            }
        )

    player_rel = relation_by_player_id[normalized_player_id]
    unique_matchweeks = len(set([r["matchweek"] for r in results]))
    avg_points_per_matchweek = (
        round((player_rel.points or 0) / unique_matchweeks, 1)
        if unique_matchweeks > 0
        else 0
    )

    a = {
        "player": _serialize_shuffle_player_relation(player_rel),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "winRate": win_rate,
        "totalGames": len(results),
        "points": player_rel.points or 0,
        "bestWinDiff": best_win_diff,
        "worstLossDiff": worst_loss_diff,
        "currentStreak": current_streak,
        "divisionsPlayed": divisions_sorted,
        "highestDivision": min(divisions_sorted) if divisions_sorted else 0,
        "lowestDivision": max(divisions_sorted) if divisions_sorted else 0,
        "biggestWins": biggest_wins,
        "worstLosses": worst_losses,
        "avgPointsPerMatchweek": avg_points_per_matchweek,
        "snapshots": snapshots,
    }

    return a


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

    stats_1 = _compute_player_comparison_stats(
        shuffle_tournament,
        player1_id_raw,
        relation_by_player_id,
        played_matches,
        all_matches,
        matches_by_matchweek,
        ranking_position_by_player_id,
    )
    stats_2 = _compute_player_comparison_stats(
        shuffle_tournament,
        player2_id_raw,
        relation_by_player_id,
        played_matches,
        all_matches,
        matches_by_matchweek,
        ranking_position_by_player_id,
    )

    return jsonify(
        {
            "tournamentId": shuffle_tournament.id,
            "totalPlayers": len(shuffle_tournament.players_relations or []),
            "player1": stats_1,
            "player2": stats_2,
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

    match_ids = [m.id for m in shuffle_tournament.matches if m.matchweek == matchweek]
    if not match_ids:
        return jsonify({"error": "No matches found for that matchweek"}), 404

    associations = (
        Association_PlayerShuffleMatch.query.filter(
            Association_PlayerShuffleMatch.shuffle_match_id.in_(match_ids)
        )
        .filter_by(player_id=player_id)
        .all()
    )

    if not associations:
        return jsonify({"error": "Player not found in that matchweek"}), 404

    removed_count = 0
    for assoc in associations:
        assoc.delete()
        removed_count += 1

    shuffle_tournament = ShuffleTournament.query.filter_by(
        id=tournament_id
    ).first_or_404()
    shuffle_tournament.recalculate_player_stats()
    return jsonify({"removedAssociations": removed_count})


@bp.route("/calculate_divisions", methods=["POST"])
@jwt_required()
def calculate_divisions():
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

    shuffle_tournament.recalculate_player_stats()
    shuffle_tournament = ShuffleTournament.query.filter_by(
        id=shuffle_tournament.id
    ).first_or_404()

    ordered_relations = sorted(
        shuffle_tournament.players_relations,
        key=lambda rel: (
            -(rel.points or 0),
            -(rel.games_played or 0),
            -((rel.games_won or 0) - (rel.games_lost or 0)),
            -(
                rel.player.ranking_points
                if rel.player and rel.player.ranking_points is not None
                else 0
            ),
            shuffle_tournament._draw_order_for_player(rel.player_id),
        ),
    )

    total_divisions = max(1, int(shuffle_tournament.number_of_divisions or 1))
    slots_per_division = 8
    for idx, rel in enumerate(ordered_relations):
        rel.division_number = min((idx // slots_per_division) + 1, total_divisions)

    shuffle_tournament.save()
    return jsonify(serialize_shuffle_tournament(shuffle_tournament))


@bp.route("/generate_matchweek", methods=["POST"])
@jwt_required()
def generate_matchweek():
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
    if not shuffle_tournament.players_relations:
        return jsonify({"error": "No players in tournament"}), 400

    unfinished_matches = [
        m
        for m in shuffle_tournament.matches
        if (not m.played) or m.score1 is None or m.score2 is None
    ]
    if unfinished_matches:
        return (
            jsonify(
                {
                    "error": "Cannot generate a new matchweek while there are unfinished matches."
                }
            ),
            400,
        )

    new_matchweek = int(shuffle_tournament.current_matchweek or 0) + 1
    created_matches = 0

    by_division = {}
    for rel in shuffle_tournament.players_relations:
        by_division.setdefault(rel.division_number, []).append(rel)

    for division_number in sorted(by_division.keys()):
        relations = sorted(
            by_division[division_number],
            key=lambda rel: (
                rel.position or 9999,
                -(rel.points or 0),
                rel.player_id,
            ),
        )
        if len(relations) < 8:
            continue

        player_ids = [rel.player_id for rel in relations[:8]]
        pairs = [
            (player_ids[0], player_ids[7]),
            (player_ids[1], player_ids[6]),
            (player_ids[2], player_ids[5]),
            (player_ids[3], player_ids[4]),
        ]

        # All pairs play all other pairs once:
        # p0-vs-p1, p0-vs-p2, p0-vs-p3, p1-vs-p2, p1-vs-p3, p2-vs-p3
        pair_matchups = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
        for a, b in pair_matchups:
            match = ShuffleMatch(
                shuffle_tournament_id=shuffle_tournament.id,
                matchweek=new_matchweek,
                division=int(division_number),
                played=False,
            )
            match.create()

            Association_PlayerShuffleMatch(
                player_id=pairs[a][0], shuffle_match_id=match.id, team="Home"
            ).create()
            Association_PlayerShuffleMatch(
                player_id=pairs[a][1], shuffle_match_id=match.id, team="Home"
            ).create()
            Association_PlayerShuffleMatch(
                player_id=pairs[b][0], shuffle_match_id=match.id, team="Away"
            ).create()
            Association_PlayerShuffleMatch(
                player_id=pairs[b][1], shuffle_match_id=match.id, team="Away"
            ).create()
            created_matches += 1

    if created_matches == 0:
        return jsonify({"error": "No divisions with enough players (minimum 8)"}), 400

    shuffle_tournament.current_matchweek = new_matchweek
    shuffle_tournament.save()
    shuffle_tournament = ShuffleTournament.query.filter_by(
        id=shuffle_tournament.id
    ).first_or_404()
    shuffle_tournament.recalculate_player_stats()
    return jsonify(serialize_shuffle_tournament(shuffle_tournament))


@bp.route("/create", methods=["POST"])
@jwt_required()
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
        current_matchweek = 0
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

    players_per_division = 8

    tournament = ShuffleTournament(
        title=title,
        current_matchweek=current_matchweek,
        max_players=max_players,
        number_of_divisions=number_of_divisions,
        has_ended=has_ended,
    )
    tournament.division_multipliers = division_multipliers
    tournament.create()

    for item in sorted(parsed_players, key=lambda x: x["order_index"]):
        division_number = ((item["order_index"] - 1) // players_per_division) + 1
        division_number = min(division_number, number_of_divisions)

        Association_PlayerShuffleTournament(
            player_id=item["player_id"],
            shuffle_tournament_id=tournament.id,
            division_number=division_number,
            position=item["order_index"],
        ).create()

    tournament.recalculate_player_stats()
    return jsonify(serialize_shuffle_tournament(tournament)), 201
