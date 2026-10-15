"""Sponsors for the footer. GET never writes: clicks are counted by the existing
redirect /sponsors/sponsor_click/<id> (modules/sponsors.py), which clickUrl points at."""

from flask import Blueprint, jsonify
from sqlalchemy.orm import joinedload

from padel_league.models import Sponsor

from . import serializers as ser
from ._http import register_error_handlers

bp = Blueprint("api_v2_sponsors", __name__, url_prefix="/api/v2")
register_error_handlers(bp)


@bp.route("/sponsors", methods=["GET"])
def list_sponsors():
    sponsors = Sponsor.query.options(joinedload(Sponsor.image)).order_by(Sponsor.id).all()
    return jsonify(
        [
            {
                "id": s.id,
                "name": s.name,
                "website": s.website,
                "clickUrl": s.url,  # url_for the click-counting redirect
                "image": ser.image(s.image),
            }
            for s in sponsors
        ]
    )
