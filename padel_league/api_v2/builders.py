"""Competition creation (admin): POST /competitions/preview and POST /competitions.

Clássica: S1's services.classica_builder plans the next edition from the previous one
(promotion, withdrawals, newcomers); S5's services.editions.create_edition_from_plan
writes groups, entries and fixtures.
Shuffle / Teams builders are not written yet (409 not_available).
"""

import inspect
from datetime import date, datetime, time

from flask import Blueprint, jsonify
from padel_league.models import Player
from padel_league.models.v2 import FORMATS, Season
from padel_league.services import editions as editions_service
from padel_league.sql_db import db

from . import serializers as ser
from ._http import bad_request, conflict, int_arg, json_body, register_error_handlers, role_required
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


def fresh_divisions(body):
    """A first edition (no previous one): playerIds then newPlayerIds, 8 per division."""
    notes = []
    players = body["player_ids"] + [p for p in body["new_players"] if p not in body["player_ids"]]
    chunks = [players[i : i + DIVISION_SIZE] for i in range(0, len(players), DIVISION_SIZE)]
    ratings = _ratings(len(chunks))
    if chunks and len(chunks[-1]) < DIVISION_SIZE:
        notes.append(f"A última divisão tem {len(chunks[-1])} jogadores; precisa de {DIVISION_SIZE}.")
    return [(i + 1, ratings[i], chunk) for i, chunk in enumerate(chunks)], notes


def division_name(competition_name, tier):
    return f"{competition_name} - {tier}ª Divisão"


def _s1_plan(body):
    """S1's services.classica_builder.next_classica_plan → (S5 plan, notes): the verified
    port of the league's rollover (2 up / 2 down, withdrawals cascade, newcomers fill)."""
    from padel_league.services.classica_builder import next_classica_plan

    if body["from_id"] is None:
        return None
    if get_competition(body["from_id"]).format != "classica":
        raise bad_request("fromCompetitionId tem de ser uma Clássica.", "invalid_input")
    # A dry run needs no real date (the preview shows groups only); create requires startsOn.
    starts_on = body["starts_on"] or date.today()
    return next_classica_plan(
        body["from_id"],
        body["name"],
        datetime.combine(starts_on, DEFAULT_KICKOFF).isoformat(),
        withdrawals=body["withdrawals"],
        new_player_ids=body["new_players"],
        season=body["season"].name,
        event_slot=body["event_slot"],
    )


def _plan_and_notes(body):
    """(plan divisions as [(tier, rating, player_ids, name)], notes, plan or None)."""
    s1 = _s1_plan(body)
    if s1 is not None:
        plan, notes = s1
        divisions = [(i, d["rating"], d["players"], d["name"]) for i, d in enumerate(plan["divisions"], 1)]
        return divisions, list(notes), plan
    divisions, notes = fresh_divisions(body)
    return [(t, r, ids, division_name(body["name"], t)) for t, r, ids in divisions], notes, None


def preview(body):
    if body["format"] != "classica":
        return {
            "groups": [],
            "notes": ["Os grupos da Shuffle e da Teams formam-se em cada etapa, não na criação."],
        }
    divisions, notes, _ = _plan_and_notes(body)
    players = {
        p.id: p for p in Player.query.filter(Player.id.in_([pid for _, _, ids, _ in divisions for pid in ids]))
    }
    return {
        "groups": [
            {
                "name": name,
                "tier": tier,
                "rating": rating,
                "players": [ser.player_ref(players[pid]) for pid in ids if pid in players],
            }
            for tier, rating, ids, name in divisions
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
    divisions, _, plan = _plan_and_notes(body)
    if plan is None:
        plan = {
            "edition_name": body["name"],
            "season": body["season"].name,
            "beginning_datetime": datetime.combine(body["starts_on"], DEFAULT_KICKOFF).isoformat(),
            "divisions": [{"name": name, "rating": rating, "players": ids} for _, rating, ids, name in divisions],
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
