"""CompetitionCard: everything a Tournaments-page card needs, for many competitions at once.

A fixed number of queries whatever the number of competitions: competitions+seasons,
stages, groups, round date range, entry counts, images.
"""

from collections import defaultdict
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from padel_league.model import Image
from padel_league.models.v2 import Competition, CompetitionGroup, Entry, Round, Stage
from padel_league.sql_db import db

from . import serializers as ser


def current_stage(stages):
    """The running stage; else the last ended one; else the first (planned)."""
    stages = sorted(stages, key=lambda s: s.number)
    if not stages:
        return None
    running = [s for s in stages if s.status == "running"]
    if running:
        return running[0]
    ended = [s for s in stages if s.status == "ended"]
    return ended[-1] if ended else stages[0]


class CardData:
    """Pre-loaded aggregates for a set of competitions."""

    def __init__(self, competitions):
        ids = [c.id for c in competitions]
        self.stages = defaultdict(list)
        self.groups = defaultdict(list)
        self.round_range = {}
        self.player_count = {}
        self.images = {}
        if not ids:
            return
        for s in Stage.query.filter(Stage.competition_id.in_(ids)).order_by(Stage.number):
            self.stages[s.competition_id].append(s)
        stage_ids = [s.id for ss in self.stages.values() for s in ss]
        if stage_ids:
            for g in (
                CompetitionGroup.query.filter(CompetitionGroup.stage_id.in_(stage_ids))
                .order_by(CompetitionGroup.tier.nullslast(), CompetitionGroup.id)
            ):
                self.groups[g.stage_id].append(g)
        rows = (
            db.session.query(Stage.competition_id, func.min(Round.date), func.max(Round.date))
            .join(Round, Round.stage_id == Stage.id)
            .filter(Stage.competition_id.in_(ids))
            .group_by(Stage.competition_id)
        )
        self.round_range = {cid: (lo, hi) for cid, lo, hi in rows}
        rows = (
            db.session.query(Entry.competition_id, func.count(Entry.id))
            .filter(Entry.competition_id.in_(ids), Entry.status == "active")
            .group_by(Entry.competition_id)
        )
        self.player_count = dict(rows)
        image_ids = {
            i for gs in self.groups.values() for g in gs for i in (g.logo_image_id, g.large_picture_id) if i
        }
        if image_ids:
            self.images = {i.id: i for i in Image.query.filter(Image.id.in_(image_ids))}

    def card_groups(self, comp):
        stg = current_stage(self.stages.get(comp.id, []))
        return self.groups.get(stg.id, []) if stg else []

    def dates(self, comp):
        lo, hi = self.round_range.get(comp.id, (None, None))
        return comp.starts_on or lo, comp.ends_on or hi


def card(comp, data, today=None):
    groups = data.card_groups(comp)
    top = groups[0] if groups else None
    starts_on, ends_on = data.dates(comp)
    return {
        "id": comp.id,
        "name": comp.name or comp.title or f"Competição {comp.id}",
        "title": comp.title or None,
        "format": comp.format,
        "formatLabel": ser.FORMAT_LABELS.get(comp.format, comp.format),
        "eventSlot": comp.event_slot.key if comp.event_slot else None,
        "season": ser.season(comp.season, today),
        "status": ser.COMPETITION_STATUS.get(comp.status, comp.status),
        "startsOn": ser.iso_date(starts_on),
        "endsOn": ser.iso_date(ends_on),
        "groupCount": len(groups),
        "playerCount": data.player_count.get(comp.id, 0),
        "coverImage": ser.image(data.images.get(top.logo_image_id)) if top else None,
        "bannerImage": ser.image(data.images.get(top.large_picture_id)) if top else None,
        "legacyEditionId": comp.id if comp.format == "classica" else None,
    }


def base_query():
    return Competition.query.options(joinedload(Competition.season), joinedload(Competition.event_slot))


def is_listed(comp, data):
    """Hide empty shells (edition 14): no groups and no players. Teams before its
    divisions are formed has players but no groups, and stays listed."""
    has_groups = any(data.groups.get(s.id) for s in data.stages.get(comp.id, []))
    return has_groups or data.player_count.get(comp.id, 0) > 0


def sort_key(card_json):
    """Current season first, then newest season, then start date descending (undated last)."""
    s = card_json["season"]
    starts = card_json["startsOn"] or "0000-00-00"
    return (not s["isCurrent"], _neg(s["startsOn"] or "0000-00-00"), _neg(starts), -card_json["id"])


def _neg(iso):
    # Descending order on ISO date strings.
    return tuple(-ord(c) for c in iso)


def cards(competitions, today=None):
    today = today or date.today()
    data = CardData(competitions)
    out = [card(c, data, today) for c in competitions if is_listed(c, data)]
    return sorted(out, key=sort_key)
