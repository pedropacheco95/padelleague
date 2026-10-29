import datetime

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required, verify_jwt_in_request

from padel_league.models import Division, Match, ShuffleMatch
from padel_league.models.v2 import CompetitionGroup
from padel_league.services import results
from padel_league.sql_db import db

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


# Any signed-in player may enter results (cerebrum decision 2026-10-15: only the
# super admins are admins; every signed-in player may enter results, mark absences
# and refresh standings). Same role as v2 PUT /api/v2/matches/<id>/result.
@bp.route("/<int:id>/edit", methods=["POST"])
@jwt_required()
def edit_match(id):
    match = Match.query.filter_by(id=id).first_or_404()
    data = request.get_json() or {}
    actor = _current_user_id()

    # Remove eliminated players from every match of this matchweek in this
    # division, recording the absence.
    for item in data.get("playersEliminated", []):
        player_id = item.get("playerId")
        if player_id:
            results.mark_absent(match.division_id, match.matchweek, int(player_id), actor_user_id=actor)

    results.record_result(
        match.id,
        data.get("homeGames"),
        data.get("awayGames"),
        court=data.get("field"),
        actor_user_id=actor,
    )
    db.session.commit()

    group = db.session.get(CompetitionGroup, match.division_id)
    try:
        results.after_result_commit(group)
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception("[match-edit] close-out failed division=%s: %s", group.id, exc)

    db.session.expire_all()
    return jsonify(serialize_match(Match.query.filter_by(id=id).first()))


# Signed-in player level on purpose, see edit_match above.
@bp.route("/<id>/edit_shuffle", methods=["POST"])
@jwt_required()
def edit_shuffle_match(id):
    shuffle_match = ShuffleMatch.query.filter_by(id=int(id)).first_or_404()
    data = request.get_json() or {}

    results.record_result(
        shuffle_match.match_id,
        data.get("homeGames"),
        data.get("awayGames"),
        actor_user_id=_current_user_id(),
    )
    db.session.commit()
    db.session.expire_all()

    shuffle_match = ShuffleMatch.query.filter_by(id=int(id)).first()
    # Stats and positions are recomputed in memory only; discard them after
    # building the response (they live in read-only views).
    with db.session.no_autoflush:
        if shuffle_match.shuffle_tournament:
            shuffle_match.shuffle_tournament.recalculate_player_stats(persist=False)
        response = jsonify(serialize_shuffle_match(shuffle_match))
    db.session.rollback()
    return response


def _current_user_id():
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        return int(identity) if identity else None
    except Exception:  # noqa: BLE001
        return None
