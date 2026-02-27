from flask import Blueprint, jsonify

from padel_league.models import Division, Edition, News, Sponsor
from padel_league.modules.frontend_api.v1.serializers import (
    serialize_division,
    serialize_edition,
    serialize_news,
    serialize_sponsor,
)

bp = Blueprint("api_v1_main", __name__, url_prefix="/api/v1/main")


@bp.route("/index", methods=["GET"])
def index():
    latest_news = News.query.filter_by(latest=True).order_by(News.id.desc()).first()
    all_news = (
        News.query.filter_by(latest=False).order_by(News.id.desc()).limit(3).all()
    )
    last_edition = Edition.query.order_by(Edition.id.desc()).first()
    divisions_to_play = (
        Division.query.filter_by(has_ended=False).order_by(Division.id.asc()).all()
    )
    sponsors = Sponsor.query.all()

    return jsonify(
        {
            "latestNews": serialize_news(latest_news),
            "allNews": [serialize_news(n, short=True) for n in all_news],
            "lastEdition": serialize_edition(last_edition) if last_edition else None,
            "tournaments": [
                serialize_division(d, short=True) for d in divisions_to_play
            ],
            "sponsors": [serialize_sponsor(s) for s in sponsors],
        }
    )
