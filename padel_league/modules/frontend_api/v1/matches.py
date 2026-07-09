import datetime

from flask import Blueprint, current_app, jsonify, request

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
    players_eliminated = False
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
                    match_was_played = mw_match.played
                    assoc.delete()
                    if match_was_played:
                        players_eliminated = True

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
            match.played = True

    match.save()

    # Always recompute the division standings from scratch so re-edits to
    # an already-played match update points/wins/games. add_match_to_table
    # was incremental and gated on first-time edits, leaving classification
    # stale on every subsequent edit. Also recompute when a player was
    # eliminated/substituted from an already-played match, even if no score
    # was submitted in this call — otherwise the removed player keeps their
    # stale points until a later score edit happens to also be present.
    # players_eliminated is only True when the removal affected a PLAYED
    # match — get_match_relations_played() (used by update_table) ignores
    # unplayed matches, so removing a player from one changes nothing.
    if (home_games is not None and away_games is not None) or players_eliminated:
        match.division.standings_up_to_date = False
        match.division.save()
        try:
            match.division.update_table(force_update=True)
        except Exception as exc:  # noqa: BLE001
            current_app.logger.exception(
                "[match-edit] update_table failed division=%s match=%s: %s",
                match.division_id,
                match.id,
                exc,
            )

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
