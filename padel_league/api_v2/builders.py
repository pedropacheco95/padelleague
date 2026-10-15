"""Competition creation (admin): POST /competitions/preview and POST /competitions.

Clássica: next edition's divisions from the previous competition's standings via
services.promotion (2 up / 2 down, withdrawals cascade), newcomers fill the bottom,
then S5's services.editions.create_edition_from_plan writes groups, entries and fixtures.
Shuffle / Teams builders are not written yet (409 not_available).
"""

import inspect
from datetime import date, datetime, time

from flask import Blueprint, jsonify
from sqlalchemy import func

from padel_league.models import Player
from padel_league.models.v2 import FORMATS, CompetitionGroup, MatchParticipant, Season, Stage
from padel_league.services import editions as editions_service
from padel_league.services import promotion
from padel_league.sql_db import db

from . import _domain
from . import serializers as ser
from ._http import bad_request, conflict, int_arg, json_body, register_error_handlers, role_required
from .cards import current_stage
from .competitions import competition_detail, get_competition

bp = Blueprint("api_v2_builders", __name__, url_prefix="/api/v2")
register_error_handlers(bp)

DIVISION_SIZE = 8
FIRST_RATING = 2000
DEFAULT_KICKOFF = time(21, 30)  # the league's usual first-round slot


def _ids(value, name):
    if value is None:
        return []
    if not isinstance(value, list):
        raise bad_request(f"{name} tem de ser uma lista.", "invalid_input")
    return [int_arg(v, name, required=True) for v in value]


def parse_body():
    data = json_body()
    fmt = data.get("format")
    if fmt not in FORMATS:
        raise bad_request("format inválido.", "invalid_input")
    name = (data.get("name") or "").strip()
    if not name:
        raise bad_request("name em falta.", "missing_parameter")
    season_id = int_arg(data.get("seasonId"), "seasonId", required=True)
    season = db.session.get(Season, season_id)
    if season is None:
        raise bad_request("Época desconhecida.", "invalid_input")
    starts_on = data.get("startsOn")
    if starts_on:
        try:
            starts_on = date.fromisoformat(starts_on)
        except (TypeError, ValueError):
            raise bad_request("startsOn inválido (AAAA-MM-DD).", "invalid_input")
    return {
        "format": fmt,
        "name": name,
        "season": season,
        "event_slot": data.get("eventSlot"),
        "starts_on": starts_on,
        "from_id": int_arg(data.get("fromCompetitionId"), "fromCompetitionId"),
        "withdrawals": _ids(data.get("withdrawals"), "withdrawals"),
        "new_players": _ids(data.get("newPlayerIds"), "newPlayerIds"),
        "player_ids": _ids(data.get("playerIds"), "playerIds"),
    }


def _ratings(n, previous=()):
    previous = list(previous)
    out = []
    for i in range(n):
        if i < len(previous) and previous[i]:
            out.append(int(previous[i]))
        else:
            last = out[-1] if out else FIRST_RATING * 2
            out.append(max(1, round(last / 2)))
    return out


def _career_appearances(player_ids):
    rows = (
        db.session.query(MatchParticipant.player_id, func.count(MatchParticipant.id))
        .filter(MatchParticipant.player_id.in_(player_ids))
        .group_by(MatchParticipant.player_id)
    )
    return dict(rows)


def classica_divisions(body):
    """[(tier, rating, [player_id] )], notes — nothing written."""
    notes = []
    if body["from_id"] is None:
        players = body["player_ids"] + [p for p in body["new_players"] if p not in body["player_ids"]]
        chunks = [players[i : i + DIVISION_SIZE] for i in range(0, len(players), DIVISION_SIZE)]
        ratings = _ratings(len(chunks))
        if chunks and len(chunks[-1]) < DIVISION_SIZE:
            notes.append(f"A última divisão tem {len(chunks[-1])} jogadores; precisa de {DIVISION_SIZE}.")
        return [(i + 1, ratings[i], chunk) for i, chunk in enumerate(chunks)], notes

    previous = get_competition(body["from_id"])
    if previous.format != "classica":
        raise bad_request("fromCompetitionId tem de ser uma Clássica.", "invalid_input")
    stage = current_stage(Stage.query.filter_by(competition_id=previous.id).all())
    groups = (
        CompetitionGroup.query.filter_by(stage_id=stage.id).order_by(CompetitionGroup.tier).all() if stage else []
    )
    if not groups:
        raise conflict("A competição anterior não tem divisões.", "no_previous_groups")

    standings = []
    for g in groups:
        for row in _domain.group_standings(g.id).rows:
            standings.append(
                {"player_id": row.player_id, "division": g.tier, "place": row.place, "appearances": row.appearances}
            )
    career = _career_appearances([s["player_id"] for s in standings])
    for s in standings:
        s["career_appearances"] = career.get(s["player_id"], 0)
    try:
        layout, decisions = promotion.next_edition_layout(standings, withdrawn=body["withdrawals"], size=DIVISION_SIZE)
    except promotion.PromotionError as exc:
        raise conflict(str(exc), "promotion_failed")

    names = {p.id: p.name for p in Player.query.filter(Player.id.in_([d["player_id"] for d in decisions]))}
    for d in decisions:
        notes.append(f"{names.get(d['player_id'], d['player_id'])} → {d['division']}ª: {d['role']} ({d['reason']})")

    newcomers = [p for p in body["new_players"] if all(p not in v for v in layout.values())]
    tiers = sorted(layout)
    for tier in tiers:  # holes cascade to the bottom; fill top-down anyway
        while len(layout[tier]) < DIVISION_SIZE and newcomers:
            layout[tier].append(newcomers.pop(0))
    while len(newcomers) >= DIVISION_SIZE:
        tiers.append(tiers[-1] + 1)
        layout[tiers[-1]], newcomers = newcomers[:DIVISION_SIZE], newcomers[DIVISION_SIZE:]
        notes.append(f"Nova {tiers[-1]}ª divisão com {DIVISION_SIZE} estreantes.")
    if newcomers:
        notes.append(f"{len(newcomers)} estreante(s) sem lugar (não chegam para uma divisão).")
    for tier in tiers:
        if len(layout[tier]) < DIVISION_SIZE:
            notes.append(f"{tier}ª divisão: faltam {DIVISION_SIZE - len(layout[tier])} jogadores.")
    ratings = _ratings(len(tiers), [g.rating for g in groups])
    return [(tier, ratings[i], layout[tier]) for i, tier in enumerate(tiers)], notes


def division_name(competition_name, tier):
    return f"{competition_name} - {tier}ª Divisão"


def preview(body):
    if body["format"] != "classica":
        return {
            "groups": [],
            "notes": ["Os grupos da Shuffle e da Teams formam-se em cada etapa, não na criação."],
        }
    divisions, notes = classica_divisions(body)
    players = {
        p.id: p for p in Player.query.filter(Player.id.in_([pid for _, _, ids in divisions for pid in ids]))
    }
    return {
        "groups": [
            {
                "name": division_name(body["name"], tier),
                "tier": tier,
                "rating": rating,
                "players": [ser.player_ref(players[pid]) for pid in ids if pid in players],
            }
            for tier, rating, ids in divisions
        ],
        "notes": notes,
    }


def _s5_on_v2():
    """S5's create_edition_from_plan writes v2 rows (it takes actor_user_id); the old one doesn't."""
    params = inspect.signature(editions_service.create_edition_from_plan).parameters
    return "actor_user_id" in params


@bp.route("/competitions/preview", methods=["POST"])
@role_required("admin")
def post_preview():
    return jsonify(preview(parse_body()))


@bp.route("/competitions", methods=["POST"])
@role_required("admin")
def create_competition():
    from ._http import require_user

    user = require_user()
    body = parse_body()
    if body["format"] != "classica" or not _s5_on_v2():
        raise conflict("A criação deste formato ainda não está disponível.", "not_available")
    if not body["starts_on"]:
        raise bad_request("startsOn em falta.", "missing_parameter")
    divisions, _ = classica_divisions(body)
    plan = {
        "edition_name": body["name"],
        "season": body["season"].name,
        "beginning_datetime": datetime.combine(body["starts_on"], DEFAULT_KICKOFF).isoformat(),
        "divisions": [
            {"name": division_name(body["name"], tier), "rating": rating, "players": ids}
            for tier, rating, ids in divisions
        ],
    }
    if body["event_slot"]:
        plan["event_slot"] = body["event_slot"]
    try:
        result = editions_service.create_edition_from_plan(plan, actor_user_id=user.id)
    except editions_service.EditionPlanError as exc:
        db.session.rollback()
        raise bad_request(str(exc), "invalid_plan")
    db.session.commit()
    comp = get_competition(result["edition_id"])
    return jsonify(competition_detail(comp)), 201
