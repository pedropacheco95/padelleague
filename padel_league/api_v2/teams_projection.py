"""Teams projection and partner simulator (Pedro's design), public reads.

GET /competitions/{id}/teams/projection: the divisions close() + build_divisions()
would give right now (S1 teams_divisions.project), with the pairing counters and
the one-sided declarations.
GET /competitions/{id}/teams/simulate?player=&partner=: the same layout with
(player, partner) as a pair, the player's result card and one row per other
roster player (where each partner would put them).

Ranking points and positions are the live seeding the projection itself uses
(teams_pairing.live_positions), not the published snapshot.
"""

from collections import Counter, defaultdict
from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy.orm import joinedload

from padel_league.models import Player
from padel_league.models.v2 import Entry, Pair, PartnerRequest, Stage
from padel_league.services import teams_divisions, teams_pairing
from padel_league.services.teams_pairing import PairingError

from . import serializers as ser
from ._http import ApiError, bad_request, int_arg, register_error_handlers, viewer
from .teams import mini_tournament

bp = Blueprint("api_v2_teams_projection", __name__, url_prefix="/api/v2")
register_error_handlers(bp)

MAX_SETS = 9  # 3 encontros × 3 sets: the bonus at stake is rating/100 per set won


def _key(a, b):
    return (a, b) if a < b else (b, a)


class Board:
    """Everything the projection reads besides project(): players, live ranking,
    formed pairs, declarations and who played together in which mini-tournament."""

    def __init__(self, mt):
        self.mt = mt
        self.roster = teams_pairing.roster_ids(mt)
        self.points, self.positions = teams_pairing.live_positions(mt)
        self.formed = {}  # player id -> partner id (pairs that exist now)
        for pair in teams_pairing.stage_pairs(mt):
            a, b = teams_pairing.pair_players(mt, pair)
            self.formed[a], self.formed[b] = b, a
        by_entry = dict(Entry.query.filter_by(competition_id=mt.competition_id).with_entities(Entry.id, Entry.player_id))
        self.choice = {
            by_entry[r.from_entry_id]: by_entry[r.to_entry_id]
            for r in PartnerRequest.query.filter_by(stage_id=mt.id)
            if r.from_entry_id in by_entry and r.to_entry_id in by_entry
        }
        self.together = defaultdict(list)  # {(a, b): [mini-tournament numbers]}
        others = (
            Pair.query.join(Stage, Stage.id == Pair.stage_id)
            .filter(Stage.competition_id == mt.competition_id, Pair.stage_id != mt.id)
            .with_entities(Pair.entry_a_id, Pair.entry_b_id, Stage.number)
        )
        for ea, eb, number in others:
            if ea in by_entry and eb in by_entry:
                self.together[_key(by_entry[ea], by_entry[eb])].append(number)
        self.times_together = Counter({k: len(v) for k, v in self.together.items()})
        ids = set(self.roster) | set(self.formed)
        self.players = {
            p.id: p for p in Player.query.options(joinedload(Player.picture)).filter(Player.id.in_(ids))
        }
        self.pending = [
            (a, b) for a, b in sorted(self.choice.items()) if a not in self.formed and self.choice.get(b) != a
        ]

    def played_together(self, a, b):
        return sorted(self.together.get(_key(a, b), []))

    def ref(self, pid):
        player = self.players.get(pid) or Player.query.get(pid)
        return {
            **ser.player_ref(player),
            "rankingPoints": self.points.get(pid, 0.0) or 0.0,
            "rankingPosition": self.positions.get(pid),
        }

    def is_open(self, now=None):
        deadline = self.mt.pairing_deadline
        return bool(not self.mt.pairing_closed and deadline and (now or datetime.utcnow()) <= deadline)


def _find(projection, player_id):
    """(division, pair) of the player in a projection."""
    for division in projection.divisions:
        for pair in division.pairs:
            if player_id in pair.players:
                return division, pair
    return None, None


def layout(board, projection, mine=None):
    """The stage, counters, pending declarations and divisions of a projection."""
    ranking_players = [pid for d in projection.divisions for p in d.pairs if p.formed_by == "ranking" for pid in p.players]
    slot = {
        pid: i
        for i, pid in enumerate(sorted(ranking_players, key=lambda pid: (board.positions.get(pid) or 10**9, pid)), 1)
    }
    pending_refs = [{"from": board.ref(a), "to": board.ref(b)} for a, b in board.pending]
    confirmed = len(board.formed) // 2
    divisions = []
    for d in projection.divisions:
        sums = [p.points for p in d.pairs]
        divisions.append(
            {
                "tier": d.tier,
                "name": d.name,
                "rating": d.rating,
                "minSum": min(sums) if sums else None,
                "maxSum": max(sums) if sums else None,
                "maxPlacePoints": d.rating,
                "maxBonusPoints": (d.rating or 0) / 100 * MAX_SETS,
                "pairs": [
                    {
                        "seed": p.seed,
                        "pairId": p.pair_id,
                        "players": [board.ref(pid) for pid in p.players],
                        "sum": p.points,
                        "formedBy": p.formed_by,
                        "provisional": p.pair_id is None,
                        "unpairedSlots": [slot[pid] for pid in p.players] if p.formed_by == "ranking" else None,
                        "pending": [
                            ref for (a, b), ref in zip(board.pending, pending_refs) if a in p.players or b in p.players
                        ],
                        "mine": mine is not None and mine in p.players,
                    }
                    for p in d.pairs
                ],
            }
        )
    deadline = board.mt.pairing_deadline
    return {
        "stage": {
            "id": board.mt.id,
            "number": board.mt.number,
            "pairingDeadline": ser.iso_datetime(deadline),
            "pairingOpen": board.is_open(),
            "pairingClosed": bool(board.mt.pairing_closed),
        },
        "counts": {
            "players": len(board.roster),
            "pairsTotal": len(board.roster) // 2,
            "pairsConfirmed": confirmed,
            "unpaired": len(board.roster) - 2 * confirmed,
            "pendingDeclarations": len(board.pending),
        },
        "pending": pending_refs,
        "divisions": divisions,
    }


def _project(mt, extra_pair=None):
    try:
        return teams_divisions.project(mt, extra_pair)
    except PairingError as exc:
        raise ApiError(400, str(exc), "pairing_rule")


@bp.route("/competitions/<int:competition_id>/teams/projection", methods=["GET"])
def get_projection(competition_id):
    mt = mini_tournament(competition_id)
    board = Board(mt)
    return jsonify(layout(board, _project(mt)))


def _player_arg(board):
    player_id = int_arg(request.args.get("player"), "player")
    if player_id is None:
        user = viewer()
        player_id = user.player_id if user else None
    if player_id is None:
        raise bad_request("player em falta.", "missing_parameter")
    if player_id not in board.roster:
        raise bad_request("Esse jogador não está inscrito neste mini-torneio.", "not_on_roster")
    return player_id


def _position(projection, player_id):
    division, pair = _find(projection, player_id)
    return division, pair, next(pid for pid in pair.players if pid != player_id)


STATUS = {"unpaired": "free", "declared_you": "declaredYou", "you_declared": "youDeclared"}


@bp.route("/competitions/<int:competition_id>/teams/simulate", methods=["GET"])
def simulate(competition_id):
    """The scenario layout and result card come from project(stage, (player, partner));
    the baseline and the candidate rows from S1 project_partners (one seeding for all)."""
    mt = mini_tournament(competition_id)
    board = Board(mt)
    me = _player_arg(board)
    partner_id = int_arg(request.args.get("partner"), "partner")

    sim = teams_divisions.project_partners(mt, me, selected=partner_id)
    locked = me in board.formed or not sim.choice_open
    scenario = _project(mt, (me, partner_id) if partner_id is not None else None)
    division, pair, partner = _position(scenario, me)

    tiers = {d.tier: [p.points for p in d.pairs] for d in scenario.divisions}
    result = {
        "tier": division.tier,
        "seed": pair.seed,
        "rating": division.rating,
        "maxPlacePoints": division.rating,
        "maxBonusPoints": (division.rating or 0) / 100 * MAX_SETS,
        "partner": board.ref(partner),
        "sum": pair.points,
        "sumBreakdown": [{"player": board.ref(pid), "points": board.points.get(pid, 0.0) or 0.0} for pid in pair.players],
        "gapUp": min(tiers[division.tier - 1]) - pair.points if division.tier - 1 in tiers else None,
        "marginDown": pair.points - max(tiers[division.tier + 1]) if division.tier + 1 in tiers else None,
        "playedTogether": board.played_together(me, partner),
    }

    base = sim.baseline
    candidates = []
    for opt in sim.options:
        paired_with = int(opt.status.split(":")[1]) if opt.status.startswith("paired_with:") else None
        allowed = opt.allowed and not locked
        candidates.append(
            {
                "player": board.ref(opt.player_id),
                "status": "confirmed" if paired_with is not None else STATUS[opt.status],
                "pairedWith": board.ref(paired_with) if paired_with is not None else None,
                "allowed": allowed,
                "reason": None if allowed else opt.reason,  # S1's Portuguese "why not"
                "sum": opt.pair_points if opt.pair_points is not None else sim.player_points + opt.points,
                "tier": opt.tier if allowed else None,
                "seed": opt.seed if allowed else None,
                "delta": base.tier - opt.tier if allowed and base.tier is not None else None,
                "playedTogether": list(opt.played_together),
            }
        )

    return jsonify(
        {
            **layout(board, scenario, mine=me),
            "player": board.ref(me),
            "partner": board.ref(partner_id) if partner_id is not None else None,
            "locked": locked,
            "result": result,
            "baseline": {
                "tier": base.tier,
                "seed": base.seed,
                "partner": board.ref(base.partner_id) if base.partner_id is not None else None,
                "sum": base.points,
            },
            "candidates": candidates,
        }
    )
