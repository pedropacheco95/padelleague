"""Group pages, matches and the calendar. Lists load matches with their sets,
participants and players in a fixed number of queries (no N+1)."""

from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy.orm import joinedload, selectinload

from padel_league.model import Image
from padel_league.models import Player
from padel_league.models.v2 import (
    Absence,
    Award,
    Competition,
    AwardEvent,
    CompetitionGroup,
    CompetitionMatch,
    Entry,
    GroupMember,
    MatchParticipant,
    Round,
    Stage,
)

from . import _domain
from . import serializers as ser
from ._http import bad_request, int_arg, not_found, register_error_handlers
from .cards import CardData, card

bp = Blueprint("api_v2_matches", __name__, url_prefix="/api/v2")
register_error_handlers(bp)


def match_query():
    return CompetitionMatch.query.options(
        joinedload(CompetitionMatch.round),
        selectinload(CompetitionMatch.sets),
        selectinload(CompetitionMatch.participants)
        .joinedload(MatchParticipant.player)
        .joinedload(Player.picture),
        joinedload(CompetitionMatch.group).joinedload(CompetitionGroup.stage).joinedload(Stage.competition),
    )


def absences_by_round(matches):
    """{(group_id, round_id): [Absence json]} for the members of the matches' groups.

    The substitute is known only when a round of a group has exactly one absence
    and one substitute participant.
    """
    keys = {(m.group_id, m.round_id) for m in matches}
    if not keys:
        return {}
    group_ids = {g for g, _ in keys}
    round_ids = {r for _, r in keys}
    rows = (
        Absence.query.options(joinedload(Absence.entry).joinedload(Entry.player).joinedload(Player.picture))
        .join(GroupMember, GroupMember.entry_id == Absence.entry_id)
        .filter(GroupMember.group_id.in_(group_ids), Absence.round_id.in_(round_ids))
        .add_columns(GroupMember.group_id)
        .order_by(Absence.id)
        .all()
    )
    subs = {}
    for m in matches:
        for p in m.participants:
            if p.role == "substitute":
                subs.setdefault((m.group_id, m.round_id), []).append(p.player)
    out = {}
    for absence, group_id in rows:
        if (group_id, absence.round_id) in keys:
            out.setdefault((group_id, absence.round_id), []).append(absence)
    recorders = recorded_by([a for items in out.values() for a in items])
    return {
        key: [
            ser.absence(
                a,
                key[0],
                subs[key][0] if len(items) == 1 and len(subs.get(key, [])) == 1 else None,
                recorders.get(a.created_by_user_id),
            )
            for a in items
        ]
        for key, items in out.items()
    }


def recorded_by(absences):
    """{user_id: Player} for the users who recorded these absences (one query)."""
    from padel_league.models import User

    ids = {a.created_by_user_id for a in absences if a.created_by_user_id}
    if not ids:
        return {}
    users = User.query.options(joinedload(User.player).joinedload(Player.picture)).filter(User.id.in_(ids))
    return {u.id: u.player for u in users if u.player is not None}


def serialize_matches(matches):
    absences = absences_by_round(matches)
    return [ser.match(m, absences=absences.get((m.group_id, m.round_id), [])) for m in matches]


def get_group(group_id):
    group = (
        CompetitionGroup.query.options(
            joinedload(CompetitionGroup.stage).joinedload(Stage.competition).joinedload(Competition.season),
            joinedload(CompetitionGroup.stage).joinedload(Stage.competition).joinedload(Competition.event_slot),
        )
        .filter(CompetitionGroup.id == group_id)
        .first()
    )
    if group is None:
        raise not_found("Grupo não encontrado.", "group_not_found")
    return group


def _awards(group_id):
    """{entry_id: Award} once the group is closed."""
    rows = Award.query.join(AwardEvent).filter(Award.group_id == group_id).all()
    return {a.entry_id: a for a in rows}


def standing_rows(group_id, players):
    standings = _domain.group_standings(group_id)
    awards = _awards(group_id)
    rows = []
    for r in standings.rows:
        award = awards.get(r.entry_id)
        rows.append(
            {
                "place": r.place,
                "player": ser.player_ref(players.get(r.player_id) or Player.query.get(r.player_id)),
                "points": r.points,
                "played": r.appearances,
                "wins": r.wins,
                "draws": r.draws,
                "losses": r.losses,
                "gamesWon": r.games_won,
                "gamesLost": r.games_lost,
                "setsWon": r.sets_won,
                "setsDrawn": r.sets_drawn,
                "attendancePct": r.attendance_pct,
                "rankingPlacePoints": award.place_points if award else None,
                "rankingBonusPoints": award.bonus_points if award else None,
                "nextGroupTier": r.next_group_tier,
            }
        )
    return standings.frozen, rows


def group_detail(group):
    stage = group.stage
    comp = stage.competition
    members = (
        Player.query.options(joinedload(Player.picture))
        .join(Entry, Entry.player_id == Player.id)
        .join(GroupMember, GroupMember.entry_id == Entry.id)
        .filter(GroupMember.group_id == group.id)
        .order_by(GroupMember.seed.nullslast(), GroupMember.id)
        .all()
    )
    players = {p.id: p for p in members}
    frozen, standings = standing_rows(group.id, players)
    rounds = Round.query.filter_by(stage_id=stage.id).order_by(Round.number).all()
    matches = match_query().filter(CompetitionMatch.group_id == group.id).all()

    played_rounds = sorted({m.round.number for m in matches if m.status in ("played", "walkover")})
    open_rounds = sorted({m.round.number for m in matches if m.status == "scheduled"})
    current_round = open_rounds[0] if open_rounds else (played_rounds[-1] if played_rounds else None)
    last_played = played_rounds[-1] if played_rounds else None
    last_matches = [m for m in matches if m.round.number == last_played] if last_played else []

    images = {
        i.id: i
        for i in Image.query.filter(Image.id.in_([x for x in (group.logo_image_id, group.large_picture_id) if x]))
    }
    return {
        **ser.group_summary(group, images),
        "competition": card(comp, CardData([comp])),
        "stage": {"id": stage.id, "number": stage.number, "name": stage.name},
        "members": [ser.player_ref(p) for p in members],
        "standings": standings,
        "standingsFrozen": frozen,
        "rounds": [ser.round_(r) for r in rounds],
        "currentRound": current_round,
        "lastPlayedMatches": serialize_matches(sorted(last_matches, key=lambda m: m.id)),
    }


@bp.route("/groups/<int:group_id>", methods=["GET"])
def get_group_page(group_id):
    return jsonify(group_detail(get_group(group_id)))


@bp.route("/groups/<int:group_id>/matches", methods=["GET"])
def group_matches(group_id):
    get_group(group_id)
    query = match_query().filter(CompetitionMatch.group_id == group_id)
    number = int_arg(request.args.get("round"), "round")
    if number is not None:
        query = query.join(Round, Round.id == CompetitionMatch.round_id).filter(Round.number == number)
    matches = sorted(query.all(), key=lambda m: (m.round.number, m.scheduled_at or datetime.max, m.id))
    return jsonify(serialize_matches(matches))


@bp.route("/matches/<int:match_id>", methods=["GET"])
def get_match(match_id):
    m = match_query().filter(CompetitionMatch.id == match_id).first()
    if m is None:
        raise not_found("Jogo não encontrado.", "match_not_found")
    return jsonify(serialize_matches([m])[0])


def _date_arg(name):
    value = request.args.get(name)
    if not value:
        raise bad_request(f"{name} em falta.", "missing_parameter")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise bad_request(f"{name} inválido (AAAA-MM-DD).", "invalid_parameter")


@bp.route("/calendar", methods=["GET"])
def calendar():
    """Matches scheduled in [from, to] (both days inclusive)."""
    start, end = _date_arg("from"), _date_arg("to")
    if end < start:
        raise bad_request("to é anterior a from.", "invalid_parameter")
    if (end - start).days > 366:
        raise bad_request("Intervalo demasiado longo (máx. 1 ano).", "invalid_parameter")
    query = match_query().filter(
        CompetitionMatch.scheduled_at >= datetime.combine(start, datetime.min.time()),
        CompetitionMatch.scheduled_at < datetime.combine(end + timedelta(days=1), datetime.min.time()),
    )
    group_id = int_arg(request.args.get("group"), "group")
    if group_id is not None:
        query = query.filter(CompetitionMatch.group_id == group_id)
    competition_id = int_arg(request.args.get("competition"), "competition")
    if competition_id is not None:
        query = (
            query.join(CompetitionGroup, CompetitionGroup.id == CompetitionMatch.group_id)
            .join(Stage, Stage.id == CompetitionGroup.stage_id)
            .filter(Stage.competition_id == competition_id)
        )
    matches = query.order_by(CompetitionMatch.scheduled_at, CompetitionMatch.id).all()
    return jsonify(serialize_matches(matches))


@bp.route("/competitions/<int:competition_id>/standings", methods=["GET"])
def competition_standings(competition_id):
    """Shuffle overall / Teams edition total (S1 services.standings.competition_standings).

    Clássica has none: S1 raises NotFound 'no_competition_standings' → 404."""
    from padel_league.services.standings import competition_standings as service

    from .competitions import get_competition

    get_competition(competition_id)
    rows = service(competition_id).rows
    players = {
        p.id: p
        for p in Player.query.options(joinedload(Player.picture)).filter(Player.id.in_([r.player_id for r in rows]))
    }
    return jsonify(
        [
            {
                "place": r.place,
                "player": ser.player_ref(players.get(r.player_id)),
                "points": r.points,
                "played": r.appearances,
                "wins": r.wins,
                "draws": r.draws,
                "losses": r.losses,
                "gamesWon": r.games_won,
                "gamesLost": r.games_lost,
                "setsWon": r.sets_won,
                "setsDrawn": r.sets_drawn,
                "attendancePct": r.attendance_pct,
                "rankingPlacePoints": r.ranking_place_points,
                "rankingBonusPoints": r.ranking_bonus_points,
                "nextGroupTier": r.next_group_tier,
                # Teams: one line per mini-tournament played
                "stages": [
                    {
                        "stageNumber": st.get("stage_number"),
                        "groupId": st.get("group_id"),
                        "tier": st.get("tier"),
                        "place": st.get("place"),
                        "points": st.get("points"),
                    }
                    for st in (r.stages or [])
                ],
            }
            for r in rows
        ]
    )
