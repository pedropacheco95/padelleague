"""Competition creation (admin): POST /competitions/preview and POST /competitions.

Clássica: S1's services.classica_builder plans the next edition from the previous one
(promotion, withdrawals, newcomers); S5's services.editions.create_edition_from_plan
writes groups, entries and fixtures.
Shuffle / Teams builders are not written yet (409 not_available).
"""

from datetime import date, datetime, time

from flask import Blueprint, jsonify
from padel_league.models import Player
from padel_league.models.v2 import FORMATS, Season
from padel_league.services import editions as editions_service
from padel_league.services.classica_builder import next_classica_plan
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
        "placed": _placed(data.get("placedNewPlayers")),
    }


def _placed(value):
    """placedNewPlayers: {tier: [player ids]} (Golden Ticket straight into a division)."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise bad_request("placedNewPlayers tem de ser um objeto {divisão: [jogadores]}.", "invalid_input")
    return {int_arg(t, "placedNewPlayers", required=True): _ids(ids, "placedNewPlayers") for t, ids in value.items()}


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


def _s1_plan(body, strict=True):
    """S1's services.classica_builder.next_classica_plan → (S5 plan, notes): the verified
    port of the league's rollover (2 up / 2 down, withdrawals cascade, newcomers fill)."""
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
        placed_new_players=body["placed"],
        season=body["season"].name,
        event_slot=body["event_slot"],
        strict=strict,  # lenient for the preview (short divisions become notes); strict for create
    )


def _plan_and_notes(body, strict=True):
    """(plan divisions as [(tier, rating, player_ids, name)], notes, plan or None)."""
    s1 = _s1_plan(body, strict)
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
    divisions, notes, plan = _plan_and_notes(body, strict=False)
    if plan is not None:
        # S5 validates the plan exactly as create would (names unique, 8 players, …):
        # a problem becomes a note here, a 400 on create.
        try:
            checked = editions_service.preview_plan(plan)
            divisions = [(d["tier"], d["rating"], d["players"], d["name"]) for d in checked["divisions"]]
        except editions_service.EditionPlanError as exc:
            notes.append(f"O plano ainda não pode ser criado: {exc}")
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
    if body["format"] != "classica":
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


@bp.route("/competitions/<int:competition_id>/fixtures", methods=["POST"])
@role_required("admin")
def generate_fixtures(competition_id):
    """Fixtures for every group of a stage (default: the current one), as one transaction
    (S5 services.fixtures.generate_group_fixtures). firstRoundDate sets the start of
    groups that have none yet (first round at the league's usual 21:30)."""
    from padel_league.models.v2 import CompetitionGroup, Stage
    from padel_league.services import fixtures as fixtures_service

    from ._http import not_found, require_user
    from .cards import current_stage

    user = require_user()
    comp = get_competition(competition_id)
    if comp.format != "classica":
        raise conflict("Só a Clássica gera calendário de uma vez.", "not_classica")
    data = json_body()
    stage_id = int_arg(data.get("stageId"), "stageId")
    stages = Stage.query.filter_by(competition_id=comp.id).all()
    stage = next((s for s in stages if s.id == stage_id), None) if stage_id else current_stage(stages)
    if stage is None:
        raise not_found("Etapa não encontrada nesta competição.", "stage_not_found")
    first = data.get("firstRoundDate")
    if first:
        try:
            first = datetime.combine(date.fromisoformat(first), DEFAULT_KICKOFF)
        except (TypeError, ValueError):
            raise bad_request("firstRoundDate inválido (AAAA-MM-DD).", "invalid_input")
    groups = CompetitionGroup.query.filter_by(stage_id=stage.id).order_by(CompetitionGroup.tier).all()
    if not groups:
        raise conflict("Esta etapa não tem divisões.", "no_groups")
    try:
        for group in groups:
            if first and group.starts_at is None:
                group.starts_at = first
            fixtures_service.generate_group_fixtures(group, commit=False, actor_user_id=user.id)
    except fixtures_service.FixtureGenerationError as exc:
        db.session.rollback()
        raise conflict(str(exc), "fixtures_not_generated")
    db.session.commit()
    db.session.expire_all()
    return jsonify(competition_detail(get_competition(competition_id)))
