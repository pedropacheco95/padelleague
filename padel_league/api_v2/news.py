"""News for the Home page (list newest first, latest, one article)."""

from flask import Blueprint, jsonify
from sqlalchemy.orm import joinedload

from padel_league.models import News

from . import serializers as ser
from ._http import not_found, register_error_handlers

bp = Blueprint("api_v2_news", __name__, url_prefix="/api/v2")
register_error_handlers(bp)


def news_json(n, full=False):
    out = {
        "id": n.id,
        "title": n.title,
        "author": n.author,
        "latest": bool(n.latest),
        "coverImage": ser.image(n.cover_image),
    }
    if full:
        out["text"] = n.text
    return out


def _query():
    return News.query.options(joinedload(News.cover_image))


@bp.route("/news", methods=["GET"])
def list_news():
    return jsonify([news_json(n) for n in _query().order_by(News.id.desc())])


@bp.route("/news/latest", methods=["GET"])
def latest_news():
    n = _query().filter(News.latest.is_(True)).order_by(News.id.desc()).first() or _query().order_by(News.id.desc()).first()
    if n is None:
        raise not_found("Ainda não há notícias.", "news_not_found")
    return jsonify(news_json(n, full=True))


@bp.route("/news/<int:news_id>", methods=["GET"])
def get_news(news_id):
    n = _query().filter(News.id == news_id).first()
    if n is None:
        raise not_found("Notícia não encontrada.", "news_not_found")
    return jsonify(news_json(n, full=True))
