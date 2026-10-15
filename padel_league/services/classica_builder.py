"""The next Clássica from the previous one: promotion on v2 standings → an edition plan.

services.promotion holds the pure rule (2 up / 2 down, withdrawal cascade).
This module feeds it the previous competition's final standings from v2
(group tier = division) and turns the layout into the plan dict that
services.editions.create_edition_from_plan (S5) validates and writes.
New players fill the vacancies from the bottom division up, in the order given.
"""

from padel_league.domain.errors import Conflict, InvalidInput, NotFound
from padel_league.models.v2 import Competition, CompetitionGroup, Entry, GroupMember, Stage, StandingSnapshot
from padel_league.services import promotion
from padel_league.services.standings import group_standings
from padel_league.sql_db import db

DIVISION_SIZE = 8


def previous_standings(competition_id):
    """Flat standings for services.promotion: player_id, division, place, appearances, career_appearances."""
    competition = db.session.get(Competition, competition_id)
    if competition is None or competition.format != "classica":
        raise NotFound(f"Clássica {competition_id} não existe.", "competition_not_found")
    groups = (
        CompetitionGroup.query.join(Stage, Stage.id == CompetitionGroup.stage_id)
        .filter(Stage.competition_id == competition_id)
        .order_by(CompetitionGroup.tier)
        .all()
    )
    if not groups:
        raise Conflict("A competição anterior não tem divisões.", "no_groups")
    if any(not g.has_ended for g in groups):
        raise Conflict("A competição anterior ainda não terminou.", "previous_not_ended")
    rows = []
    for group in groups:
        for r in group_standings(group.id).rows:
            rows.append({"player_id": r.player_id, "division": group.tier, "place": r.place, "appearances": r.appearances})
    career = _career_appearances([r["player_id"] for r in rows], competition)
    for r in rows:
        r["career_appearances"] = career.get(r["player_id"], 0)
    return groups, rows


def _career_appearances(player_ids, upto):
    """Appearances in every finished group up to and including competition `upto`."""
    q = (
        db.session.query(Entry.player_id, db.func.coalesce(db.func.sum(StandingSnapshot.appearances), 0))
        .join(StandingSnapshot, StandingSnapshot.entry_id == Entry.id)
        .join(Competition, Competition.id == Entry.competition_id)
        .filter(Entry.player_id.in_(player_ids), StandingSnapshot.group_member_id.isnot(None))
    )
    if upto.ends_on is not None:
        q = q.filter((Competition.ends_on <= upto.ends_on) | (Competition.id == upto.id))
    return {pid: int(n) for pid, n in q.group_by(Entry.player_id).all()}


def next_classica_plan(
    previous_competition_id,
    edition_name,
    beginning_datetime,
    withdrawals=(),
    new_player_ids=(),
    placed_new_players=None,
    season=None,
    event_slot=None,
    division_prefix=None,
    strict=True,
):
    """Returns (plan, notes). Nothing is written.

    `placed_new_players` ({tier: [player_id]}) puts newcomers straight into a
    division (e.g. a Golden Ticket into the 1ª); those slots are not cascaded.
    The rest of `new_player_ids` fill the remaining vacancies bottom-up.
    The plan has the previous edition's ratings per tier and group names
    "<prefix> - Nª Divisão". With strict (for creating), raises InvalidInput
    when the newcomers do not exactly fill the vacancies; with strict=False
    (for a preview) short divisions or leftover newcomers become notes.
    """
    placed = {int(t): [int(p) for p in ids] for t, ids in (placed_new_players or {}).items()}
    groups, standings = previous_standings(previous_competition_id)
    previous_ids = {s["player_id"] for s in standings}
    withdrawals = [int(p) for p in withdrawals]
    unknown = set(withdrawals) - previous_ids
    if unknown:
        raise InvalidInput(f"Desistências que não jogaram a edição anterior: {sorted(unknown)}.", "unknown_withdrawal")
    newcomers = [int(p) for p in new_player_ids] + [p for ids in placed.values() for p in ids]
    clash = set(newcomers) & (previous_ids - set(withdrawals))
    if clash or len(set(newcomers)) != len(newcomers):
        raise InvalidInput(f"Jogadores novos repetidos ou já presentes: {sorted(clash)}.", "duplicate_new_player")

    reserved = {t: len(ids) for t, ids in placed.items()}
    layout, decisions = promotion.next_edition_layout(
        standings, withdrawn=withdrawals, reserved=reserved, size=DIVISION_SIZE
    )
    for tier, ids in placed.items():
        layout[tier].extend(ids)
    open_slots = {t: n for t, n in promotion.vacancies(layout, size=DIVISION_SIZE).items() if n > 0}
    queue = [p for p in newcomers if p not in {x for ids in placed.values() for x in ids}]
    needed = sum(open_slots.values())
    if strict and needed != len(queue):
        raise InvalidInput(
            f"Há {needed} vagas e {len(queue)} jogadores novos; têm de ser iguais.", "vacancies_mismatch"
        )
    notes = [f"{d['role']}: jogador {d['player_id']} ({d['reason']})" for d in decisions]
    for tier, ids in placed.items():
        notes += [f"jogador novo {pid} entra diretamente na {tier}ª divisão" for pid in ids]
    for tier in sorted(open_slots, reverse=True):
        for _ in range(open_slots[tier]):
            if not queue:
                break
            pid = queue.pop(0)
            layout[tier].append(pid)
            notes.append(f"jogador novo {pid} entra na {tier}ª divisão")
    for tier in sorted(layout):
        if len(layout[tier]) < DIVISION_SIZE:
            notes.append(f"{tier}ª divisão: faltam {DIVISION_SIZE - len(layout[tier])} jogadores.")
    if queue:
        notes.append(f"{len(queue)} jogador(es) novo(s) sem vaga: {queue}.")

    prefix = division_prefix or edition_name
    rating = {g.tier: g.rating for g in groups}
    plan = {
        "edition_name": edition_name,
        "beginning_datetime": str(beginning_datetime),
        "divisions": [
            {"name": f"{prefix} - {tier}ª Divisão", "rating": rating[tier], "players": layout[tier]}
            for tier in sorted(layout)
        ],
    }
    if season:
        plan["season"] = season
    if event_slot:
        plan["event_slot"] = event_slot
    return plan, notes


def members_of(competition_id):
    """{tier: [player_id]} of a Clássica, for comparing a plan with what was approved."""
    rows = (
        db.session.query(CompetitionGroup.tier, Entry.player_id)
        .join(GroupMember, GroupMember.group_id == CompetitionGroup.id)
        .join(Entry, Entry.id == GroupMember.entry_id)
        .join(Stage, Stage.id == CompetitionGroup.stage_id)
        .filter(Stage.competition_id == competition_id)
        .all()
    )
    out = {}
    for tier, pid in rows:
        out.setdefault(tier, set()).add(pid)
    return out
