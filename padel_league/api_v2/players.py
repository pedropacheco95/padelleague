"""Players, player history and comparison, rankings and the ranking explanation."""

from collections import defaultdict

from flask import Blueprint, jsonify, request
from sqlalchemy import text
from sqlalchemy.orm import joinedload

from padel_league.models import Player
from padel_league.services import ranking
from padel_league.models.v2 import (
    Award,
    Competition,
    CompetitionMatch,
    CompetitionGroup,
    Entry,
    GroupMember,
    MatchParticipant,
    RankingEntry,
    RankingSnapshot,
    Season,
    Stage,
    StandingSnapshot,
)

from . import serializers as ser
from ._http import int_arg, not_found, register_error_handlers
from .cards import CardData, base_query, card
from .matches import match_query, serialize_matches

bp = Blueprint("api_v2_players", __name__, url_prefix="/api/v2")
register_error_handlers(bp)

# Outside substitutes (players.status = 'external', SUBS_ import) stay out of the
# players list and the ranking; their profile is still reachable by id.
NOT_EXTERNAL = text("players.status <> 'external'")


def external_ids(player_ids):
    if not player_ids:
        return set()
    return {
        pid
        for pid, in Player.query.filter(Player.id.in_(player_ids), text("players.status = 'external'")).with_entities(
            Player.id
        )
    }


# --- ranking lookups ----------------------------------------------------------------


def current_snapshot():
    return ranking.current_snapshot()


def ranking_table(snapshot):
    """[(position, player_id, points)] ordered; a missing position follows the points order.

    Players without points under the current rule are unranked (not listed; their
    rankingPosition is null) — an intended difference from v1 (S6)."""
    if snapshot is None:
        return []
    rows = [e for e in RankingEntry.query.filter_by(snapshot_id=snapshot.id) if (e.points or 0) > 0]
    hidden = external_ids([e.player_id for e in rows])
    rows = [e for e in rows if e.player_id not in hidden]
    rows.sort(key=lambda e: (-(e.points or 0), e.position or 10**9, e.player_id))
    return [(e.position or i, e.player_id, e.points) for i, e in enumerate(rows, 1)]


def ranking_by_player(snapshot):
    return {pid: (pos, pts) for pos, pid, pts in ranking_table(snapshot)}


def _status_by_player(player_ids):
    """active: an entry this season; inactive: entries only before; substitute: never entered."""
    today_season = [s.id for s in Season.query.all() if ser.season(s)["isCurrent"]]
    rows = (
        Entry.query.join(Competition, Competition.id == Entry.competition_id)
        .filter(Entry.player_id.in_(player_ids))
        .with_entities(Entry.player_id, Competition.season_id)
        .all()
    )
    seasons = defaultdict(set)
    for pid, season_id in rows:
        seasons[pid].add(season_id)
    return {
        pid: "active" if seasons[pid] & set(today_season) else "inactive" if seasons[pid] else "substitute"
        for pid in player_ids
    }


def player_summary(player, ranking, status):
    pos, pts = ranking.get(player.id, (None, 0.0))
    return {**ser.player_ref(player), "rankingPosition": pos, "rankingPoints": pts or 0.0, "status": status}


def get_player(player_id):
    player = Player.query.options(joinedload(Player.picture), joinedload(Player.large_picture)).get(player_id)
    if player is None:
        raise not_found("Jogador não encontrado.", "player_not_found")
    return player


@bp.route("/players", methods=["GET"])
def list_players():
    players = Player.query.options(joinedload(Player.picture)).filter(NOT_EXTERNAL).order_by(Player.name).all()
    ranking = ranking_by_player(current_snapshot())
    status = _status_by_player([p.id for p in players])
    out = [player_summary(p, ranking, status[p.id]) for p in players]
    out.sort(key=lambda p: (p["rankingPosition"] is None, p["rankingPosition"] or 0, p["name"]))
    return jsonify(out)


# --- player page ----------------------------------------------------------------------


def history(player_id):
    """One row per competition entry, newest first."""
    entries = Entry.query.filter_by(player_id=player_id).all()
    if not entries:
        return []
    comps = base_query().filter(Competition.id.in_([e.competition_id for e in entries])).all()
    data = CardData(comps)
    by_comp = {c.id: c for c in comps}
    entry_ids = [e.id for e in entries]
    # Latest group per entry (Shuffle has one per stage).
    groups = (
        GroupMember.query.join(CompetitionGroup, CompetitionGroup.id == GroupMember.group_id)
        .join(Stage, Stage.id == CompetitionGroup.stage_id)
        .filter(GroupMember.entry_id.in_(entry_ids))
        .with_entities(GroupMember.entry_id, GroupMember.id, CompetitionGroup.id, CompetitionGroup.name, Stage.number)
        .all()
    )
    latest = {}
    for entry_id, member_id, group_id, name, number in groups:
        if entry_id not in latest or number > latest[entry_id][3]:
            latest[entry_id] = (member_id, group_id, name, number)
    # A snapshot belongs to its group member; 48 legacy rows have no member and are
    # matched by their own entry only (never through a missing member id).
    by_member, by_entry = {}, {}
    for snap in StandingSnapshot.query.filter(StandingSnapshot.entry_id.in_(entry_ids)):
        if snap.group_member_id is not None:
            by_member[snap.group_member_id] = snap
        else:
            by_entry[snap.entry_id] = snap
    award_points = defaultdict(float)
    for a in Award.query.filter(Award.entry_id.in_(entry_ids)):
        award_points[a.entry_id] += a.total
    rows = []
    for e in entries:
        comp = by_comp[e.competition_id]
        member_id, group_id, group_name, _ = latest.get(e.id, (None, None, None, None))
        snap = by_member.get(member_id) if member_id is not None else by_entry.get(e.id)
        rows.append(
            {
                "competition": card(comp, data),
                "groupId": group_id,
                "groupName": group_name,
                "place": snap.place if snap else e.final_place,
                "points": snap.points if snap else None,
                # Matches played, as v1's tournamentHistory (S6 gate 2); group standings show jornadas.
                "played": snap.appearances if snap else None,
                "wins": snap.wins if snap else None,
                "draws": snap.draws if snap else None,
                "losses": snap.losses if snap else None,
                "awardPoints": award_points.get(e.id),
            }
        )
    rows.sort(key=lambda r: (r["competition"]["startsOn"] or "", r["competition"]["id"]), reverse=True)
    return rows


def player_matches(player_id, competition_id=None, role=None):
    """The player's matches; role 'member' (their own seat) or 'substitute' narrows them."""
    seats = MatchParticipant.query.filter_by(player_id=player_id)
    if role is not None:
        seats = seats.filter_by(role=role)
    query = match_query().filter(CompetitionMatch.id.in_(seats.with_entities(MatchParticipant.match_id)))
    if competition_id is not None:
        query = (
            query.join(CompetitionGroup, CompetitionGroup.id == CompetitionMatch.group_id)
            .join(Stage, Stage.id == CompetitionGroup.stage_id)
            .filter(Stage.competition_id == competition_id)
        )
    return query.order_by(CompetitionMatch.scheduled_at.desc().nullslast(), CompetitionMatch.id.desc()).all()


def _side(match, player_id):
    return next((p.side for p in match.participants if p.player_id == player_id), None)


def _result_for(match, side):
    """'win' | 'draw' | 'loss' | None (not played) from the match score."""
    home, away, winner = ser.match_score(match, match.group.stage.competition.format)
    if winner is None or side is None:
        return None
    if winner == "draw":
        return "draw"
    return "win" if winner == side else "loss"


def match_stats(matches, player_id, subs_matches=()):
    """S3's PlayerDetail.stats keys, from v2 facts (real jornadas, not v1's 3-per-week estimate).

    `matches` are the player's member matches; substitute appearances only add
    subsMatches (played ones), so attendance stays within the player's own groups."""
    played = won = drawn = lost = games_won = games_lost = 0
    rounds_played = set()
    for m in matches:
        side = _side(m, player_id)
        result = _result_for(m, side)
        if result is None:
            continue
        played += 1
        won += result == "win"
        drawn += result == "draw"
        lost += result == "loss"
        rounds_played.add((m.group_id, m.round_id))
        for s in m.sets:
            mine, theirs = (s.home_games, s.away_games) if side == "home" else (s.away_games, s.home_games)
            games_won += mine or 0
            games_lost += theirs or 0

    # Jornadas of the player's groups that were played (any result), whether or not they played.
    member_groups = (
        GroupMember.query.join(Entry, Entry.id == GroupMember.entry_id)
        .filter(Entry.player_id == player_id)
        .with_entities(GroupMember.group_id)
    )
    group_rounds = set(
        CompetitionMatch.query.filter(
            CompetitionMatch.group_id.in_(member_groups), CompetitionMatch.status.in_(("played", "walkover"))
        )
        .with_entities(CompetitionMatch.group_id, CompetitionMatch.round_id)
        .distinct()
    )
    tournaments = (
        Entry.query.join(GroupMember, GroupMember.entry_id == Entry.id)
        .filter(Entry.player_id == player_id)
        .with_entities(Entry.competition_id)
        .distinct()
        .count()
    )
    weeks_played = len(rounds_played)
    weeks_missed = len(group_rounds - rounds_played)
    weeks_total = weeks_played + weeks_missed
    return {
        "matchesPlayed": played,
        "matchesWon": won,
        "matchesLost": lost,
        "matchesDrawn": drawn,
        "efficiency": won / played * 100 if played else 0.0,
        "tournamentsPlayed": tournaments,
        "matchweeksPlayed": weeks_played,
        "matchweeksMissed": weeks_missed,
        "matchweeksPerTournament": weeks_played / tournaments if tournaments else 0.0,
        "attendance": weeks_played / weeks_total * 100 if weeks_total else 0.0,
        "gamesWon": games_won,
        "gamesLost": games_lost,
        "subsMatches": sum(_result_for(m, _side(m, player_id)) is not None for m in subs_matches),
    }


@bp.route("/players/<int:player_id>", methods=["GET"])
def get_player_page(player_id):
    player = get_player(player_id)
    ranking = ranking_by_player(current_snapshot())
    status = _status_by_player([player.id])[player.id]
    subs = player_matches(player.id, role="substitute")
    return jsonify(
        {
            **player_summary(player, ranking, status),
            "largePictureUrl": player.large_picture_url,
            "preferredHand": player.prefered_hand,
            "preferredPosition": player.prefered_position,
            "height": player.height,
            "birthDate": ser.iso_date(player.birthday),
            "history": history(player.id),
            "stats": match_stats(player_matches(player.id, role="member"), player.id, subs),
            "substituteMatches": serialize_matches(subs),
        }
    )


@bp.route("/players/<int:player_id>/matches", methods=["GET"])
def get_player_matches(player_id):
    get_player(player_id)
    competition_id = int_arg(request.args.get("competition"), "competition")
    return jsonify(serialize_matches(player_matches(player_id, competition_id)))


@bp.route("/players/compare", methods=["GET"])
def compare():
    a_id = int_arg(request.args.get("a"), "a", required=True)
    b_id = int_arg(request.args.get("b"), "b", required=True)
    a, b = get_player(a_id), get_player(b_id)
    ranking = ranking_by_player(current_snapshot())
    status = _status_by_player([a.id, b.id])
    # Member seats only: a substitute appearance is not the player's own record.
    a_matches = {m.id: m for m in player_matches(a.id, role="member")}
    shared = [m for m in player_matches(b.id, role="member") if m.id in a_matches]
    h2h = {"played": 0, "aWins": 0, "bWins": 0, "draws": 0}
    together = {"played": 0, "wins": 0, "draws": 0, "losses": 0}
    for m in shared:
        side_a, side_b = _side(m, a.id), _side(m, b.id)
        result = _result_for(m, side_a)
        if result is None:
            continue
        if side_a == side_b:
            together["played"] += 1
            together[{"win": "wins", "draw": "draws", "loss": "losses"}[result]] += 1
        else:
            h2h["played"] += 1
            h2h[{"win": "aWins", "draw": "draws", "loss": "bWins"}[result]] += 1
    return jsonify(
        {
            "a": player_summary(a, ranking, status[a.id]),
            "b": player_summary(b, ranking, status[b.id]),
            "headToHead": h2h,
            "together": together,
            "matches": serialize_matches(shared),
        }
    )


# --- rankings ------------------------------------------------------------------------


def ranking_json(snapshot):
    table = ranking_table(snapshot)
    previous = (
        RankingSnapshot.query.filter(
            RankingSnapshot.is_dry_run.is_(False),
            RankingSnapshot.league_id == snapshot.league_id,
            RankingSnapshot.id < snapshot.id,
        )
        .order_by(RankingSnapshot.id.desc())
        .first()
    )
    before = ranking_by_player(previous) if previous else {}
    players = {
        p.id: p
        for p in Player.query.options(joinedload(Player.picture)).filter(Player.id.in_([pid for _, pid, _ in table]))
    }
    return {
        "snapshotId": snapshot.id,
        "rule": {"key": snapshot.rule.key, "name": snapshot.rule.name},
        "computedAt": ser.iso_datetime(snapshot.computed_at),
        "entries": [
            {
                "position": pos,
                "player": ser.player_ref(players[pid]),
                "points": pts,
                "previousPosition": before.get(pid, (None, None))[0],
            }
            for pos, pid, pts in table
        ],
    }


@bp.route("/rankings/current", methods=["GET"])
def current_ranking():
    snapshot = current_snapshot()
    if snapshot is None:
        raise not_found("Ainda não há ranking.", "no_ranking")
    return jsonify(ranking_json(snapshot))


@bp.route("/rankings/<int:snapshot_id>", methods=["GET"])
def ranking_snapshot(snapshot_id):
    snapshot = RankingSnapshot.query.get(snapshot_id)
    if snapshot is None:
        raise not_found("Ranking não encontrado.", "ranking_not_found")
    return jsonify(ranking_json(snapshot))


def _explain_lines(player_id):
    """S1 ranking.explain: one line per award, counted or not, with the reason (Portuguese)."""
    return [
        {
            "competition_id": line.competition_id,
            "stage_number": line.stage_number,
            "place": line.place,
            "place_points": line.place_points,
            "bonus_points": line.bonus_points,
            "counted": line.counted,
            "reason": line.reason,
        }
        for line in ranking.explain(player_id)
    ]


@bp.route("/rankings/players/<int:player_id>", methods=["GET"])
def explain_player(player_id):
    player = get_player(player_id)
    snapshot = current_snapshot()
    lines = _explain_lines(player.id)
    comps = base_query().filter(Competition.id.in_({line["competition_id"] for line in lines})).all()
    data = CardData(comps)
    by_id = {c.id: c for c in comps}
    total = ranking_by_player(snapshot).get(player.id, (None, 0.0))[1] or 0.0
    out = [
        {
            "competition": card(by_id[line["competition_id"]], data),
            "stageNumber": line["stage_number"],
            "place": line["place"],
            "placePoints": line["place_points"],
            "bonusPoints": line["bonus_points"],
            "counted": line["counted"],
            "reason": line["reason"],
        }
        for line in lines
    ]
    out.sort(key=lambda l: (l["competition"]["startsOn"] or "", l["competition"]["id"]), reverse=True)
    return jsonify({"player": ser.player_ref(player), "total": total, "lines": out})
