import datetime

from flask import Blueprint, jsonify, request

from padel_league.models import Association_PlayerMatch, Division, Match, ShuffleMatch

from .serializers import serialize_division, serialize_match, serialize_shuffle_match

bp = Blueprint("api_v1_matches", __name__, url_prefix="/api/v1/matches")


@bp.route("/for_edit")
def for_edit():
    division_id = request.args.get("division_id")
    if division_id:
        division = Division.query.filter_by(id=int(division_id)).first_or_404()
        matches = division.matches
    else:
        matches = Match.query.all()

    divisions = Division.query.filter_by(has_ended=False).all()
    tomorrow = datetime.datetime.combine(
        datetime.date.today() + datetime.timedelta(days=1),
        datetime.datetime.min.time(),
    )
    matches = [
        m for m in matches if m.date_hour and m.date_hour <= tomorrow and not m.played
    ]
    return jsonify(
        {
            "matches": [serialize_match(m) for m in matches],
            "divisions": [serialize_division(d, short=True) for d in divisions],
        }
    )


@bp.route("/<int:id>/edit", methods=["POST"])
def edit_match(id):
    match = Match.query.filter_by(id=id).first_or_404()
    data = request.get_json()

    # Remove player from ALL matches in this matchweek in this division
    for item in data.get("playersEliminated", []):
        player_id = item.get("playerId")
        if not player_id:
            continue
        for mw_match in match.division.matches:
            if mw_match.matchweek == match.matchweek:
                assoc = Association_PlayerMatch.query.filter_by(
                    match_id=mw_match.id, player_id=player_id
                ).first()
                if assoc:
                    assoc.delete()

    home_games = data.get("homeGames")
    away_games = data.get("awayGames")
    field = data.get("field")

    if home_games is not None:
        match.games_home_team = int(home_games)
    if away_games is not None:
        match.games_away_team = int(away_games)
    if field is not None:
        match.field = field

    if home_games is not None and away_games is not None:
        h, a = int(home_games), int(away_games)
        match.winner = 1 if h > a else (-1 if a > h else 0)
        if not match.played:
            try:
                match.division.add_match_to_table(match)
            except Exception:
                pass
            match.played = True

    match.save()
    return jsonify(serialize_match(match))


@bp.route("/<id>/edit_shuffle", methods=["POST"])
def edit_shuffle_match(id):
    shuffle_match = ShuffleMatch.query.filter_by(id=int(id)).first_or_404()
    data = request.get_json() or {}

    home_games = data.get("homeGames")
    away_games = data.get("awayGames")

    if home_games is not None:
        shuffle_match.score1 = int(home_games)
    if away_games is not None:
        shuffle_match.score2 = int(away_games)

    if home_games is not None and away_games is not None:
        shuffle_match.played = True

    shuffle_match.save()

    if shuffle_match.shuffle_tournament:
        shuffle_match.shuffle_tournament.recalculate_player_stats()

    return jsonify(serialize_shuffle_match(shuffle_match))
