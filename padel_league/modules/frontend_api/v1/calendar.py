import datetime

from flask import Blueprint, jsonify, request, url_for
from sqlalchemy.orm import joinedload

from padel_league.models import Match

bp = Blueprint("api_v1_calendar", __name__, url_prefix="/api/v1/calendar")


def _parse_month(month_str):
    if not month_str:
        today = datetime.date.today()
        return datetime.date(today.year, today.month, 1)

    try:
        year_str, month_value = month_str.split("-")
        year = int(year_str)
        month = int(month_value)
        if month < 1 or month > 12:
            raise ValueError
        return datetime.date(year, month, 1)
    except (ValueError, TypeError):
        return None


def _next_month(first_day):
    if first_day.month == 12:
        return datetime.date(first_day.year + 1, 1, 1)
    return datetime.date(first_day.year, first_day.month + 1, 1)


@bp.route("", methods=["GET"])
@bp.route("/", methods=["GET"])
@bp.route("/<int:division_id>", methods=["GET"])
def calendar_month(division_id=None):
    month_param = request.args.get("month")
    month_start = _parse_month(month_param)
    if not month_start:
        return jsonify({"error": "month must be in YYYY-MM format"}), 400

    month_end = _next_month(month_start)

    query = Match.query.options(joinedload(Match.division)).filter(
        Match.date_hour >= datetime.datetime.combine(month_start, datetime.time.min),
        Match.date_hour < datetime.datetime.combine(month_end, datetime.time.min),
    )
    if division_id is not None:
        query = query.filter(Match.division_id == division_id)

    matches = query.order_by(Match.date_hour.asc(), Match.id.asc()).all()

    events = []
    for match in matches:
        home_names = [player.name for player in match.home_players()]
        away_names = [player.name for player in match.away_players()]

        events.append(
            {
                "id": match.id,
                "title": f"{' / '.join(home_names) or 'Substituto'} vs {' / '.join(away_names) or 'Substituto'}",
                "divisionId": match.division_id,
                "divisionName": match.division.name if match.division else None,
                "dateHour": match.date_hour.isoformat() if match.date_hour else None,
                "played": bool(match.played),
                "gamesHomeTeam": match.games_home_team,
                "gamesAwayTeam": match.games_away_team,
                "href": url_for("matches.match", id=match.id),
            }
        )

    return jsonify(
        {
            "month": month_start.strftime("%Y-%m"),
            "startsOn": month_start.isoformat(),
            "endsBefore": month_end.isoformat(),
            "divisionId": division_id,
            "events": events,
        }
    )
