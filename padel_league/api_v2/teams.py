"""Teams pair choice, scoped to one competition (services/teams_pairing does the work).

Same TeamsState shape as v1 GET /api/v1/teams/, but per competition id.
"""

from datetime import datetime

from flask import Blueprint, jsonify

from padel_league.models import Player
from padel_league.models.v2 import Stage
from padel_league.services import teams_divisions, teams_pairing
from padel_league.services.teams_pairing import PairingError
from padel_league.sql_db import db

from . import serializers as ser
from ._http import (
    ApiError,
    bad_request,
    has_role,
    int_arg,
    json_body,
    not_found,
    register_error_handlers,
    require_user,
    role_required,
    viewer,
)
from .competitions import get_competition

bp = Blueprint("api_v2_teams", __name__, url_prefix="/api/v2")
register_error_handlers(bp)


def mini_tournament(competition_id):
    """The latest stage that opened pair choice; before that, the first stage."""
    comp = get_competition(competition_id)
    if comp.format != "teams":
        raise not_found("Esta competição não é uma Teams.", "not_teams")
    stages = Stage.query.filter_by(competition_id=comp.id).order_by(Stage.number).all()
    if not stages:
        raise not_found("Ainda não há mini-torneios.", "no_mini_tournament")
    opened = [s for s in stages if s.pairing_deadline is not None]
    return opened[-1] if opened else stages[0]


def _preload_roster(mt):
    """Load roster players with pictures in one query; teams_pairing's per-entry
    lazy loads then hit the identity map instead of the database. The caller must
    hold the returned list: the identity map only keeps weak references."""
    from sqlalchemy.orm import joinedload

    from padel_league.models.v2 import Entry

    ids = Entry.query.filter_by(competition_id=mt.competition_id).with_entities(Entry.player_id)
    return Player.query.options(joinedload(Player.picture)).filter(Player.id.in_(ids)).all()


def state(mt, user=None):
    roster = _preload_roster(mt)  # held: keeps them in the (weak) identity map
    assert roster is not None
    # Same ranking as /players and /rankings (current snapshot), not the legacy
    # players.ranking_* mirror; unranked players have no position (0 in this schema).
    from .players import current_snapshot, ranking_by_player

    ranking = ranking_by_player(current_snapshot())

    def rank(pid):
        pos, pts = ranking.get(pid, (None, 0.0))
        return pos or 0, pts or 0.0
    players = teams_pairing.roster_players(mt)
    by_id = {p.id: p for p in players}
    pairs = teams_pairing.stage_pairs(mt)
    pair_players = {p.id: teams_pairing.pair_players(mt, p) for p in pairs}
    missing = {pid for ids in pair_players.values() for pid in ids} - set(by_id)
    if missing:  # a paired player who left the roster
        by_id.update({p.id: p for p in Player.query.filter(Player.id.in_(missing))})
    paired = {pid for ids in pair_players.values() for pid in ids}
    my_id = user.player_id if user else None
    in_roster = my_id is not None and my_id in {p.id for p in players}

    ranked = {pid: rank(pid) for pid in by_id}
    players.sort(key=lambda p: (ranked[p.id][0] == 0, ranked[p.id][0], p.name))

    my_choice, chose_me = None, []
    if in_roster:
        my_choice = teams_pairing.choice_of(mt, my_id)
        chose_me = [pid for pid in teams_pairing.chose(mt, my_id) if pid not in paired]

    history = teams_pairing.times_together(mt)
    deadline = mt.pairing_deadline
    pair_points = {pair.id: sum(rank(pid)[1] for pid in pair_players[pair.id]) for pair in pairs}
    # Parelhas card (Pedro, 30 Oct): can this pair move up/down next time? Only once the divisions exist.
    movements = teams_divisions.pair_movements(teams_divisions.formed_divisions(mt, pair_points))

    return {
        "miniTournament": {
            "id": mt.id,
            "number": mt.number,
            "pairingDeadline": ser.iso_datetime(deadline),
            "pairingClosed": bool(mt.pairing_closed),
            "pairingOpen": bool(not mt.pairing_closed and deadline and datetime.utcnow() <= deadline),
        },
        "players": [
            {
                **ser.player_ref(p),
                "rankingPoints": rank(p.id)[1],
                "rankingPosition": rank(p.id)[0],
                "paired": p.id in paired,
                # No partner already played with in 3 mini-tournaments.
                "allowedForMe": bool(in_roster and p.id != my_id and teams_pairing.allowed(my_id, p.id, history)),
            }
            for p in players
        ],
        "pairs": [
            {
                "id": pair.id,
                "source": ser.PAIR_SOURCE.get(pair.formed_by, "auto"),
                "players": [ser.player_ref(by_id[pid]) for pid in pair_players[pair.id]],
                "rankingPoints": pair_points[pair.id],
                "movement": ser.pair_movement(movements.get(pair.id)),
            }
            for pair in pairs
        ],
        "me": {
            "playerId": my_id,
            "inRoster": in_roster,
            "myChoice": my_choice,
            "choseMe": chose_me,
            "pairId": next((pid for pid, ids in pair_players.items() if my_id in ids), None),
            "isAdmin": has_role(user, "admin"),
        },
    }


def _run(competition_id, action):
    """Run a pairing action, then answer the fresh state or the rule it broke (400)."""
    mt = mini_tournament(competition_id)
    user = require_user()
    try:
        action(mt, user)
    except PairingError as exc:
        db.session.rollback()
        raise ApiError(400, str(exc), "pairing_rule")
    return jsonify(state(mt, user))


def _own_player(user):
    if user.player_id is None:
        raise PairingError("A tua conta não está associada a um jogador.")
    return user.player_id


@bp.route("/competitions/<int:competition_id>/teams", methods=["GET"])
def get_state(competition_id):
    return jsonify(state(mini_tournament(competition_id), viewer()))


@bp.route("/competitions/<int:competition_id>/partner-requests", methods=["POST"])
@role_required("player")
def choose_partner(competition_id):
    partner_id = int_arg(json_body().get("partnerId"), "partnerId", required=True)
    return _run(competition_id, lambda mt, user: teams_pairing.declare(mt, _own_player(user), partner_id))


@bp.route("/competitions/<int:competition_id>/partner-requests", methods=["DELETE"])
@role_required("player")
def withdraw_partner(competition_id):
    return _run(competition_id, lambda mt, user: teams_pairing.withdraw(mt, _own_player(user)))


@bp.route("/competitions/<int:competition_id>/pairs", methods=["POST"])
@role_required("admin")
def admin_set_pair(competition_id):
    ids = json_body().get("playerIds") or []
    if not isinstance(ids, list) or len(ids) != 2:
        raise bad_request("Indica dois jogadores.")
    a, b = (int_arg(i, "playerIds", required=True) for i in ids)
    return _run(competition_id, lambda mt, user: teams_pairing.set_pair(mt, a, b))


@bp.route("/competitions/<int:competition_id>/pairs/<int:pair_id>", methods=["DELETE"])
@role_required("admin")
def admin_unpair(competition_id, pair_id):
    return _run(competition_id, lambda mt, user: teams_pairing.unpair(mt, pair_id))


@bp.route("/competitions/<int:competition_id>/pairs/close", methods=["POST"])
@role_required("admin")
def admin_close_pairing(competition_id):
    return _run(competition_id, lambda mt, user: teams_pairing.close(mt))


@bp.route("/competitions/<int:competition_id>/roster/<int:player_id>", methods=["POST"])
@role_required("admin")
def admin_add_to_roster(competition_id, player_id):
    if Player.query.get(player_id) is None:
        raise not_found("Jogador não encontrado.", "player_not_found")
    return _run(competition_id, lambda mt, user: teams_pairing.add_to_roster(mt, player_id))


@bp.route("/competitions/<int:competition_id>/roster/<int:player_id>", methods=["DELETE"])
@role_required("admin")
def admin_remove_from_roster(competition_id, player_id):
    return _run(competition_id, lambda mt, user: teams_pairing.remove_from_roster(mt, player_id))
