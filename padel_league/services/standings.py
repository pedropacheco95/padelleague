"""Group standings on the v2 model: frozen snapshot rows, or computed live.

A group whose standings were snapshotted (at close-out, or imported at
migration) returns exactly the stored rows. Otherwise the rows are computed
by padel_league.domain.standings from the played matches. Read-only.
"""

from dataclasses import dataclass

from padel_league.domain import standings as rules
from padel_league.domain.errors import NotFound
from padel_league.models.v2 import CompetitionGroup, CompetitionMatch, Entry, GroupMember, Round, StandingSnapshot
from padel_league.sql_db import db

COUNTED_STATUSES = ("played", "walkover")


@dataclass
class GroupStandings:
    group_id: int
    format: str
    frozen: bool
    rows: list  # [domain.standings.StandingRow]


def _group(group_id):
    group = db.session.get(CompetitionGroup, group_id)
    if group is None:
        raise NotFound(f"Grupo {group_id} não existe.", "group_not_found")
    return group


def group_members(group_id):
    rows = (
        db.session.query(GroupMember.id, GroupMember.entry_id, GroupMember.seed)
        .filter(GroupMember.group_id == group_id)
        .all()
    )
    players = dict(db.session.query(Entry.id, Entry.player_id).filter(Entry.id.in_([r.entry_id for r in rows])).all())
    return [rules.Member(entry_id=r.entry_id, player_id=players[r.entry_id], order=r.id) for r in rows]


def match_facts(group_id):
    """Played (or walked-over) matches of a group as domain facts; only members score."""
    matches = (
        CompetitionMatch.query.filter(
            CompetitionMatch.group_id == group_id, CompetitionMatch.status.in_(COUNTED_STATUSES)
        )
        .join(Round, Round.id == CompetitionMatch.round_id)
        .with_entities(CompetitionMatch, Round.number)
        .all()
    )
    facts = []
    for match, round_number in matches:
        sides = {"home": [], "away": []}
        for p in sorted(match.participants, key=lambda p: (p.side, p.slot)):
            if p.role == "member" and p.entry_id is not None:
                sides[p.side].append(p.entry_id)
        sets = tuple(rules.SetResult(s.home_games, s.away_games, s.outcome) for s in match.sets)
        walkover = getattr(match, "walkover_winner", None) if match.status == "walkover" else None
        facts.append(rules.MatchFacts(round_number, tuple(sides["home"]), tuple(sides["away"]), sets, walkover))
    return facts


def compute_rows(group):
    members = group_members(group.id)
    facts = match_facts(group.id)
    if group.stage.competition.format == "teams":
        return rules.teams_standings(members, facts)
    return rules.classica_standings(members, facts)


def rounds_played(group_id):
    return (
        db.session.query(db.func.max(Round.number))
        .join(CompetitionMatch, CompetitionMatch.round_id == Round.id)
        .filter(CompetitionMatch.group_id == group_id, CompetitionMatch.status.in_(COUNTED_STATUSES))
        .scalar()
        or 0
    )


def _snapshot_attendance(s, rounds):
    """Rows imported at migration store the B3 value (100% as 787.5) over a
    sometimes stale matchweek: recompute it over the rounds actually played."""
    if s.source == "legacy":
        return rules.attendance_pct(s.appearances or 0, rounds * rules.CLASSICA_MATCHES_PER_ROUND)
    return s.percentage_of_appearances


def _snapshot_rows(group_id):
    rows = (
        db.session.query(StandingSnapshot, GroupMember.id)
        .join(GroupMember, GroupMember.id == StandingSnapshot.group_member_id)
        .filter(GroupMember.group_id == group_id)
        .all()
    )
    players = dict(
        db.session.query(Entry.id, Entry.player_id).filter(Entry.id.in_([s.entry_id for s, _ in rows])).all()
    )
    rounds = rounds_played(group_id) if rows else 0
    out = [
        rules.StandingRow(
            entry_id=s.entry_id,
            player_id=players[s.entry_id],
            place=s.place,
            points=s.points,
            appearances=s.appearances,
            attendance_pct=_snapshot_attendance(s, rounds),
            wins=s.wins,
            draws=s.draws,
            losses=s.losses,
            games_won=s.games_won,
            games_lost=s.games_lost,
            order=gm_id,
        )
        for s, gm_id in rows
    ]
    return sorted(out, key=lambda r: (r.place if r.place is not None else 10**9, r.order))


def group_standings(group_id):
    group = _group(group_id)
    fmt = group.stage.competition.format
    member_count = GroupMember.query.filter_by(group_id=group_id).count()
    frozen = _snapshot_rows(group_id)
    if frozen and len(frozen) == member_count:
        if fmt == "teams":  # Teams snapshots store sets in wins/draws/losses
            for r in frozen:
                r.sets_won, r.sets_drawn, r.sets_lost = r.wins, r.draws, r.losses
        return GroupStandings(group_id, fmt, True, frozen)
    return GroupStandings(group_id, fmt, False, compute_rows(group))


# --- competition level ------------------------------------------------------------


@dataclass
class CompetitionRow(rules.StandingRow):
    ranking_place_points: float | None = None
    ranking_bonus_points: float | None = None
    next_group_tier: int | None = None
    stages: list = None  # Teams: [{stage_number, group_id, tier, place, points}]


@dataclass
class CompetitionStandings:
    competition_id: int
    format: str
    rows: list  # [CompetitionRow]


def competition_standings(competition_id):
    from padel_league.models.v2 import Competition

    competition = db.session.get(Competition, competition_id)
    if competition is None:
        raise NotFound(f"Competição {competition_id} não existe.", "competition_not_found")
    if competition.format == "teams":
        rows = _teams_edition_rows(competition)
    elif competition.format == "shuffle":
        rows = _shuffle_overall_rows(competition)
    else:
        raise NotFound("Só a Shuffle e a Teams têm classificação da competição.", "no_competition_standings")
    return CompetitionStandings(competition.id, competition.format, rows)


def _teams_edition_rows(competition):
    """Edition total = sum of the ranking points of the closed mini-tournament groups.

    Presences and sets (wins/draws/losses) add up every group played so far,
    closed or live. Ties on the total share the place.
    """
    from padel_league.models.v2 import Award, AwardEvent, Stage

    entries = Entry.query.filter_by(competition_id=competition.id).filter(Entry.status != "replaced").all()
    rows = {
        e.id: CompetitionRow(e.id, e.player_id, sets_won=0, sets_drawn=0, sets_lost=0, order=e.id, stages=[],
                             ranking_place_points=0.0, ranking_bonus_points=0.0)
        for e in entries
    }
    groups = (
        CompetitionGroup.query.join(Stage, Stage.id == CompetitionGroup.stage_id)
        .filter(Stage.competition_id == competition.id)
        .order_by(Stage.number, CompetitionGroup.tier)
        .all()
    )
    awards = {
        (a.group_id, a.entry_id): a
        for a in Award.query.join(AwardEvent, AwardEvent.id == Award.award_event_id).filter(
            AwardEvent.competition_id == competition.id
        )
    }
    for group in groups:
        for r in group_standings(group.id).rows:
            row = rows.get(r.entry_id)
            if row is None:
                continue
            row.appearances += r.appearances
            row.wins += r.wins
            row.draws += r.draws
            row.losses += r.losses
            row.sets_won += r.sets_won or 0
            row.sets_drawn += r.sets_drawn or 0
            row.sets_lost += r.sets_lost or 0
            row.games_won += r.games_won
            row.games_lost += r.games_lost
            award = awards.get((group.id, r.entry_id))
            if award is not None:
                row.ranking_place_points += award.place_points
                row.ranking_bonus_points += award.bonus_points
            row.stages.append(
                {
                    "stage_number": group.stage.number,
                    "group_id": group.id,
                    "tier": group.tier,
                    "place": r.place,
                    "set_points": r.points,
                    "ranking_points": award.total if award is not None else None,
                }
            )
    for row in rows.values():
        row.points = row.ranking_place_points + row.ranking_bonus_points
    ordered = sorted(rows.values(), key=lambda r: (-r.points, -r.appearances, r.order))
    return rules.assign_shared_places(ordered, key=lambda r: r.points)


def _shuffle_overall_rows(competition):
    """Overall Shuffle table, from the matches: 3 × group multiplier a win,
    1 × a draw (as compat.players_in_shuffle_tournament); order by points,
    presences, games difference. When the final places were stored (the
    competition-level standing rows), place and next group come from them."""
    from padel_league.models.v2 import Stage

    entries = Entry.query.filter_by(competition_id=competition.id).all()
    rows = {e.id: CompetitionRow(e.id, e.player_id, order=e.id) for e in entries}
    groups = CompetitionGroup.query.join(Stage, Stage.id == CompetitionGroup.stage_id).filter(
        Stage.competition_id == competition.id
    )
    for group in groups:
        multiplier = group.multiplier or 1
        for r in rules.classica_standings(group_members(group.id), match_facts(group.id)):
            row = rows.get(r.entry_id)
            if row is None:
                continue
            row.points += multiplier * (3 * r.wins + r.draws)
            for k in ("appearances", "wins", "draws", "losses", "games_won", "games_lost"):
                setattr(row, k, getattr(row, k) + getattr(r, k))
    ordered = sorted(rows.values(), key=lambda r: (-r.points, -r.appearances, -r.games_difference, r.order))
    for place, row in enumerate(ordered, start=1):
        row.place = place

    stored = {
        s.entry_id: s
        for s in StandingSnapshot.query.join(Entry, Entry.id == StandingSnapshot.entry_id).filter(
            Entry.competition_id == competition.id, StandingSnapshot.group_member_id.is_(None)
        )
    }
    if stored and len(stored) == len(rows) and all(s.place is not None for s in stored.values()):
        for row in ordered:
            row.place = stored[row.entry_id].place
            row.next_group_tier = stored[row.entry_id].next_division
        ordered.sort(key=lambda r: (r.place, r.order))
    return ordered
