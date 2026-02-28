import datetime
import re

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from padel_league.sql_db import db
from padel_league.models import (
    Association_PlayerDivision,
    Division,
    Edition,
    Player,
)
from padel_league.modules.frontend_api.v1.serializers import serialize_division

bp = Blueprint("api_v1_divisions", __name__, url_prefix="/api/v1/divisions")


def _json_error(message: str, status: int = 400):
    return jsonify({"error": message, "message": message}), status


def _parse_iso_datetime(value):
    if value in (None, ""):
        return None
    try:
        return datetime.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError("beginning_datetime must be a valid ISO datetime")


def _parse_iso_date(value):
    if value in (None, ""):
        return None
    try:
        return datetime.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError("end_date must be a valid ISO date (YYYY-MM-DD)")


def _extract_division_order(division_name: str):
    match = re.search(r"(\d+)", division_name or "")
    if match:
        return int(match.group(1))
    return 9999


def _validate_payload(data):
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")

    required_fields = {
        "edition_id",
        "name",
        "beginning_datetime",
        "rating",
        "end_date",
        "has_ended",
        "open_division",
        "logo_image_id",
        "large_picture_id",
        "players",
    }
    missing = [field for field in required_fields if field not in data]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(sorted(missing))}")

    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")

    try:
        edition_id = int(data["edition_id"])
    except (TypeError, ValueError):
        raise ValueError("edition_id must be an integer")

    rating_raw = data.get("rating")
    rating = None
    if rating_raw not in (None, ""):
        try:
            rating = int(float(rating_raw))
        except (TypeError, ValueError):
            raise ValueError("rating must be a number or null")

    has_ended = bool(data.get("has_ended"))
    open_division = bool(data.get("open_division"))

    logo_image_id = data.get("logo_image_id")
    if logo_image_id in ("", None):
        logo_image_id = None
    else:
        try:
            logo_image_id = int(logo_image_id)
        except (TypeError, ValueError):
            raise ValueError("logo_image_id must be an integer or null")

    large_picture_id = data.get("large_picture_id")
    if large_picture_id in ("", None):
        large_picture_id = None
    else:
        try:
            large_picture_id = int(large_picture_id)
        except (TypeError, ValueError):
            raise ValueError("large_picture_id must be an integer or null")

    beginning_datetime = _parse_iso_datetime(data.get("beginning_datetime"))
    end_date = _parse_iso_date(data.get("end_date"))

    players_payload = data.get("players") or []
    if not isinstance(players_payload, list):
        raise ValueError("players must be an array")

    parsed_players = []
    seen_player_ids = set()
    seen_order_indexes = set()

    for item in players_payload:
        if not isinstance(item, dict):
            raise ValueError("each players item must be an object")

        if "player_id" not in item or "order_index" not in item:
            raise ValueError("each players item requires player_id and order_index")

        try:
            player_id = int(item["player_id"])
            order_index = int(item["order_index"])
        except (TypeError, ValueError):
            raise ValueError("player_id and order_index must be integers")

        if order_index < 1:
            raise ValueError("order_index must be >= 1")

        if player_id in seen_player_ids:
            raise ValueError(f"duplicate player_id: {player_id}")
        if order_index in seen_order_indexes:
            raise ValueError(f"duplicate order_index: {order_index}")

        seen_player_ids.add(player_id)
        seen_order_indexes.add(order_index)
        parsed_players.append({"player_id": player_id, "order_index": order_index})

    edition = Edition.query.filter_by(id=edition_id).first()
    if not edition:
        raise ValueError(f"edition_id {edition_id} was not found")

    existing_players = (
        Player.query.filter(Player.id.in_(seen_player_ids)).all()
        if seen_player_ids
        else []
    )
    existing_player_ids = {p.id for p in existing_players}
    missing_player_ids = sorted(seen_player_ids - existing_player_ids)
    if missing_player_ids:
        raise ValueError(f"player(s) not found: {missing_player_ids}")

    return {
        "edition_id": edition_id,
        "name": name,
        "beginning_datetime": beginning_datetime,
        "rating": rating,
        "end_date": end_date,
        "has_ended": has_ended,
        "open_division": open_division,
        "logo_image_id": logo_image_id,
        "large_picture_id": large_picture_id,
        "players": sorted(parsed_players, key=lambda p: p["order_index"]),
    }


def _replace_division_players(division_id: int, players_payload):
    current_relations = Association_PlayerDivision.query.filter_by(
        division_id=division_id
    ).all()
    for rel in current_relations:
        db.session.delete(rel)

    for item in players_payload:
        db.session.add(
            Association_PlayerDivision(
                player_id=item["player_id"],
                division_id=division_id,
                place=item["order_index"],
            )
        )

    db.session.commit()


@bp.route("", methods=["POST"])
@bp.route("/", methods=["POST"])
def create_division():
    data = request.get_json() or {}

    try:
        payload = _validate_payload(data)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    division = Division(
        edition_id=payload["edition_id"],
        name=payload["name"],
        beginning_datetime=payload["beginning_datetime"],
        rating=payload["rating"],
        end_date=payload["end_date"],
        has_ended=payload["has_ended"],
        open_division=payload["open_division"],
        logo_image_id=payload["logo_image_id"],
        large_picture_id=payload["large_picture_id"],
    )

    try:
        division.create()
        _replace_division_players(division.id, payload["players"])
        return jsonify(serialize_division(division, short=True)), 201
    except IntegrityError:
        db.session.rollback()
        return _json_error("A division with this name already exists", 409)


@bp.route("/<int:id>", methods=["PUT"])
def update_division(id):
    division = Division.query.filter_by(id=id).first_or_404()
    data = request.get_json() or {}

    try:
        payload = _validate_payload(data)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    division.edition_id = payload["edition_id"]
    division.name = payload["name"]
    division.beginning_datetime = payload["beginning_datetime"]
    division.rating = payload["rating"]
    division.end_date = payload["end_date"]
    division.has_ended = payload["has_ended"]
    division.open_division = payload["open_division"]
    division.logo_image_id = payload["logo_image_id"]
    division.large_picture_id = payload["large_picture_id"]

    try:
        division.save()
        _replace_division_players(division.id, payload["players"])
        return jsonify(serialize_division(division, short=True))
    except IntegrityError:
        db.session.rollback()
        return _json_error("A division with this name already exists", 409)


@bp.route("/last_played_players", methods=["GET"])
def last_played_players():
    edition_id = request.args.get("edition_id")
    if not edition_id:
        return _json_error("edition_id is required", 400)

    try:
        edition_id = int(edition_id)
    except (TypeError, ValueError):
        return _json_error("edition_id must be an integer", 400)

    selected_edition = Edition.query.filter_by(id=edition_id).first()
    if not selected_edition:
        return _json_error(f"edition_id {edition_id} was not found", 404)

    source_edition = (
        Edition.query.filter(
            Edition.league_id == selected_edition.league_id,
            Edition.id < selected_edition.id,
        )
        .order_by(Edition.id.desc())
        .first()
    )

    # Fallback to selected edition if no previous edition exists.
    if not source_edition:
        source_edition = selected_edition

    source_divisions = sorted(
        source_edition.divisions,
        key=lambda div: (_extract_division_order(div.name), div.name.lower()),
    )

    divisions_payload = []
    for division in source_divisions:
        players = []
        try:
            ordered_players = division.players_classification()
        except Exception:
            ordered_players = [rel.player for rel in division.players_relations]

        for player in ordered_players:
            players.append(
                {
                    "id": player.id,
                    "name": player.name,
                    "pictureUrl": player.picture_url,
                }
            )

        divisions_payload.append(
            {
                "name": division.name,
                "players": players,
            }
        )

    return jsonify({"divisions": divisions_payload})
