from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy.exc import IntegrityError

from padel_league.sql_db import db
from padel_league.models import Edition, League
from padel_league.modules.frontend_api.v1.serializers import serialize_edition

bp = Blueprint("api_v1_editions", __name__, url_prefix="/api/v1/editions")


def _json_error(message: str, status: int = 400):
    return jsonify({"error": message, "message": message}), status


@bp.route("", methods=["GET"])
@bp.route("/", methods=["GET"])
def list_editions():
    editions = Edition.query.order_by(Edition.id.desc()).all()
    return jsonify(
        {"editions": [serialize_edition(edition, short=True) for edition in editions]}
    )


@bp.route("", methods=["POST"])
@bp.route("/", methods=["POST"])
@jwt_required()
def create_edition():
    data = request.get_json() or {}

    name = (data.get("name") or "").strip()
    if not name:
        return _json_error("name is required")

    league_id = data.get("league_id")
    if league_id is None:
        # Single-league setup today; default rather than force every caller
        # to look the id up.
        league = League.query.order_by(League.id.asc()).first()
        if not league:
            return _json_error("no league exists to attach the edition to")
        league_id = league.id
    else:
        try:
            league_id = int(league_id)
        except (TypeError, ValueError):
            return _json_error("league_id must be an integer")
        if not League.query.filter_by(id=league_id).first():
            return _json_error(f"league_id {league_id} was not found", 404)

    edition = Edition(name=name, league_id=league_id)
    db.session.add(edition)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _json_error("An edition with this name already exists", 409)

    return jsonify(serialize_edition(edition, short=True)), 201
