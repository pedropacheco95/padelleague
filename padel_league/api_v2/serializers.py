"""v2 JSON shapes (docs/v2/api/openapi.yaml): camelCase, ids preserved, numbers unrounded.

Built from v2 models only. Functions that need data across many rows take it
pre-loaded (see cards.py) so list endpoints stay one query per table.
"""

from datetime import date, datetime

from padel_league.domain.awards import teams_points_range

FORMAT_LABELS = {"classica": "Classic", "teams": "Teams", "shuffle": "Shuffle", "super_cup": "Super Cup"}
COMPETITION_STATUS = {"planned": "upcoming", "running": "live", "ended": "ended"}
# Pair.formed_by → TeamsState pair source
PAIR_SOURCE = {"mutual": "mutual", "ranking": "auto", "draw": "auto", "rotation": "auto", "manual": "admin"}
DEFAULT_PICTURE = "/static/images/Player/default_player.jpg"


def iso_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.date()
    return value.isoformat()


def iso_datetime(value):
    """UTC datetimes with a trailing Z; a bare date becomes midnight UTC."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day)
    return value.replace(microsecond=0).isoformat() + "Z"


def image(img):
    # Only public images are served by URL; never sign (that would call GCS).
    if img is None or not img.is_public:
        return None
    return {"url": img.public_url(), "width": None, "height": None}


def player_ref(player):
    if player is None:
        return None
    return {
        "id": player.id,
        "name": player.name,
        "fullName": player.full_name,
        "pictureUrl": player.picture_url or DEFAULT_PICTURE,
    }


def user(u):
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "role": u.role,
        "playerId": u.player_id,
        "isAdmin": u.role in ("admin", "super_admin"),
        "superAdmin": u.role == "super_admin",
    }


def season(s, today=None):
    today = today or date.today()
    return {
        "id": s.id,
        "name": s.name,
        "startsOn": iso_date(s.starts_on),
        "endsOn": iso_date(s.ends_on),
        "isCurrent": bool(s.starts_on and s.ends_on and s.starts_on <= today <= s.ends_on),
    }


CLASSICA_MATCHES_PER_ROUND = 3


def presences(fmt, appearances):
    """StandingRow.played = presenças (jornadas). Clássica stores one appearance per
    match, three per jornada; v1 shows int(appearances / 3), and so do we."""
    if appearances is None:
        return None
    return int(appearances / CLASSICA_MATCHES_PER_ROUND) if fmt == "classica" else appearances


def round_(r):
    return {"id": r.id, "number": r.number, "date": iso_date(r.date)}


def points_range(g, fmt=None):
    """Teams only: the ranking points one player can take out of the division, {min, max}."""
    if fmt is None and g.stage is not None:
        fmt = g.stage.competition.format
    if fmt != "teams" or g.rating is None:
        return None
    lo, hi = teams_points_range(float(g.rating))
    return {"min": lo, "max": hi}


def group_summary(g, images=None, fmt=None):
    """images: {image_id: Image} (v2 groups carry only the ids); fmt: the competition format when known."""
    images = images or {}
    return {
        "id": g.id,
        "name": g.name or (f"Grupo {g.tier}" if g.tier is not None else f"Grupo {g.id}"),
        "tier": g.tier,
        "rating": float(g.rating) if g.rating is not None else None,
        "pointsRange": points_range(g, fmt),
        "hasEnded": bool(g.has_ended),
        "logoImage": image(images.get(g.logo_image_id)),
        "bannerImage": image(images.get(g.large_picture_id)),
    }


def stage(s, groups=None, rounds=None, images=None):
    return {
        "id": s.id,
        "number": s.number,
        "name": s.name,
        "status": s.status,
        "emitsAward": bool(s.emits_award),
        "pairingDeadline": iso_datetime(s.pairing_deadline),
        "pairingClosed": bool(s.pairing_closed),
        "groups": [group_summary(g, images, s.competition.format) for g in (s.groups if groups is None else groups)],
        "rounds": [round_(r) for r in (s.rounds if rounds is None else rounds)],
    }


# --- matches --------------------------------------------------------------------

# Teams (Estatutos): set won 3, drawn 1 each, lost 0; a walkover is 3 sets won.
# Mirrors S1's domain.standings.teams_match_points; swap to it once merged.
SET_POINTS = {"win": 3, "draw": 1}
DRAWN_SET_OUTCOMES = ("timeout_draw", "not_started")


def match_score(m, fmt):
    """(homeScore, awayScore, winner) — games for Clássica/Shuffle, set points for Teams."""
    if m.status == "walkover":
        side = m.walkover_winner
        if side not in ("home", "away"):
            return None, None, None
        if fmt == "teams":
            pts = 3 * SET_POINTS["win"]
            return (pts, 0, side) if side == "home" else (0, pts, side)
        return None, None, side
    if m.status != "played" or not m.sets:
        return None, None, None
    if fmt == "teams":
        home = away = 0
        for s in m.sets:
            if s.outcome in DRAWN_SET_OUTCOMES or (s.home_games or 0) == (s.away_games or 0):
                home += SET_POINTS["draw"]
                away += SET_POINTS["draw"]
            elif (s.home_games or 0) > (s.away_games or 0):
                home += SET_POINTS["win"]
            else:
                away += SET_POINTS["win"]
    else:
        home = sum(s.home_games or 0 for s in m.sets)
        away = sum(s.away_games or 0 for s in m.sets)
    winner = "home" if home > away else "away" if away > home else "draw"
    return home, away, winner


def participants(m, replaces=None):
    """Always four slots; a slot with no row is an unknown substitute. A substitute's
    (or unknown) slot carries `replaces`: the member taken out of it, when recorded."""
    by_slot = {(p.side, p.slot): p for p in m.participants}
    out = []
    for side in ("home", "away"):
        for slot in (1, 2):
            p = by_slot.get((side, slot))
            seat = {
                "side": side,
                "slot": slot,
                "role": p.role if p else "unknown",
                "player": player_ref(p.player) if p else None,
            }
            if seat["role"] != "member":
                seat["replaces"] = player_ref((replaces or {}).get((side, slot)))
            out.append(seat)
    return out


def absence(a, group_id=None, substitute=None, recorded_by=None):
    """recorded_by: the Player of the user who marked it (audit); derived history has none."""
    recorded = a.source == "recorded"
    return {
        "id": a.id,
        "roundId": a.round_id,
        "groupId": group_id,
        "player": player_ref(a.entry.player),
        "substitute": player_ref(substitute),
        "kind": a.kind,
        "source": a.source,
        "recordedBy": player_ref(recorded_by) if recorded else None,
        "recordedAt": iso_datetime(a.created_at) if recorded else None,
    }


def match(m, group=None, competition=None, absences=(), replaces=None):
    group = group or m.group
    competition = competition or group.stage.competition
    home, away, winner = match_score(m, competition.format)
    return {
        "id": m.id,
        "groupId": m.group_id,
        "groupName": group.name,
        "competitionId": competition.id,
        "format": competition.format,
        "round": m.round.number,
        "scheduledAt": iso_datetime(m.scheduled_at),
        "court": m.court,
        "status": m.status,
        # Teams result saved set by set, not complete: sets below, nothing counts it yet.
        "inProgress": m.status == "scheduled" and bool(m.sets),
        "participants": participants(m, replaces),
        "sets": [
            {"setNo": s.set_no, "homeGames": s.home_games, "awayGames": s.away_games, "outcome": s.outcome}
            for s in m.sets
        ],
        "homeScore": home,
        "awayScore": away,
        "winner": winner,
        "absences": list(absences),
    }
