"""Seasons and competitions: the Tournaments cards, the competition page, current-by-format."""

from datetime import date

from flask import Blueprint, jsonify, request
from sqlalchemy.orm import joinedload

from padel_league.models.v2 import FORMATS, Competition, Round, Season, Stage

from . import serializers as ser
from ._http import bad_request, int_arg, not_found, register_error_handlers
from .cards import CardData, base_query, card, cards, current_stage, is_listed

bp = Blueprint("api_v2_competitions", __name__, url_prefix="/api/v2")
register_error_handlers(bp)

STATUS_FILTER = {v: k for k, v in ser.COMPETITION_STATUS.items()}


def _format_arg(required=False):
    fmt = request.args.get("format")
    if not fmt:
        if required:
            raise bad_request("format em falta.", "missing_parameter")
        return None
    if fmt not in FORMATS:
        raise bad_request(f"Formato desconhecido: {fmt}.", "invalid_parameter")
    return fmt


def get_competition(competition_id):
    comp = base_query().filter(Competition.id == competition_id).first()
    if comp is None:
        raise not_found("Competição não encontrada.", "competition_not_found")
    return comp


@bp.route("/seasons", methods=["GET"])
def list_seasons():
    today = date.today()
    seasons = Season.query.order_by(Season.starts_on.desc().nullslast(), Season.id.desc()).all()
    return jsonify([ser.season(s, today) for s in seasons])


@bp.route("/competitions", methods=["GET"])
def list_competitions():
    query = base_query()
    season_id = int_arg(request.args.get("season"), "season")
    if season_id is not None:
        query = query.filter(Competition.season_id == season_id)
    fmt = _format_arg()
    if fmt:
        query = query.filter(Competition.format == fmt)
    status = request.args.get("status")
    if status:
        if status not in STATUS_FILTER:
            raise bad_request(f"Estado desconhecido: {status}.", "invalid_parameter")
        query = query.filter(Competition.status == STATUS_FILTER[status])
    return jsonify(cards(query.all()))


@bp.route("/competitions/current", methods=["GET"])
def current_competition():
    """Live first; else the next upcoming; else the most recent ended one."""
    fmt = _format_arg(required=True)
    listed = cards(base_query().filter(Competition.format == fmt).all())
    if not listed:
        raise not_found("Não há competições deste formato.", "competition_not_found")
    by_status = {s: [c for c in listed if c["status"] == s] for s in ("live", "upcoming", "ended")}
    if by_status["live"]:
        return jsonify(by_status["live"][0])
    if by_status["upcoming"]:
        return jsonify(min(by_status["upcoming"], key=lambda c: (c["startsOn"] or "9999", c["id"])))
    return jsonify(max(by_status["ended"], key=lambda c: (c["endsOn"] or "", c["id"])))


def competition_detail(comp):
    data = CardData([comp])
    stages = (
        Stage.query.filter(Stage.competition_id == comp.id)
        .options(joinedload(Stage.rounds))
        .order_by(Stage.number)
        .all()
    )
    current = current_stage(stages)
    return {
        **card(comp, data),
        "rules": comp.rules or {},
        "stages": [ser.stage(s, groups=data.groups.get(s.id, []), rounds=s.rounds, images=data.images) for s in stages],
        "currentStageId": current.id if current else None,
    }


@bp.route("/competitions/<int:competition_id>", methods=["GET"])
def get_competition_page(competition_id):
    comp = get_competition(competition_id)
    if not is_listed(comp, CardData([comp])):
        raise not_found("Competição não encontrada.", "competition_not_found")
    return jsonify(competition_detail(comp))
