"""Small builders for v2 rows in Postgres tests (use with the `pg` fixture).

Each returns the flushed object; nothing commits, so the test's rollback cleans up.
"""

from datetime import date, datetime

from padel_league.models import Player
from padel_league.models.v2 import (
    Competition,
    CompetitionGroup,
    CompetitionMatch,
    Entry,
    GroupMember,
    MatchParticipant,
    MatchSet,
    Pair,
    Round,
    Season,
    Stage,
)
from padel_league.sql_db import db


def _add(obj):
    db.session.add(obj)
    db.session.flush()
    return obj


def player(name=None, **kw):
    n = db.session.query(Player).count() + 1
    return _add(Player(name=name or f"Test Player {n}-{datetime.utcnow().timestamp()}", **kw))


def competition(format="classica", name="Test competition", season_name="2026/27", **kw):
    season = Season.query.filter_by(name=season_name).one()
    return _add(Competition(season_id=season.id, format=format, name=name, status="running", **kw))


def stage(comp, number=1, **kw):
    return _add(Stage(competition_id=comp.id, number=number, **kw))


def group(stg, tier=1, rating=500, name=None, **kw):
    return _add(CompetitionGroup(stage_id=stg.id, tier=tier, rating=rating, name=name or f"Group {tier}", **kw))


def round_(stg, number=1, on=None):
    return _add(Round(stage_id=stg.id, number=number, date=on or date(2026, 10, 20)))


def entry(comp, plr, **kw):
    return _add(Entry(competition_id=comp.id, player_id=plr.id, **kw))


def member(grp, ent, seed=None, pair_id=None):
    return _add(GroupMember(group_id=grp.id, entry_id=ent.id, seed=seed, pair_id=pair_id))


def pair(stg, ent_a, ent_b, formed_by="manual"):
    a, b = sorted((ent_a.id, ent_b.id))
    return _add(Pair(stage_id=stg.id, entry_a_id=a, entry_b_id=b, formed_by=formed_by))


def match(grp, rnd, home=(), away=(), sets=(), status="scheduled", **kw):
    """home/away: entries (members). sets: [(home_games, away_games), ...]."""
    m = _add(CompetitionMatch(group_id=grp.id, round_id=rnd.id, status=status, **kw))
    for side, entries in (("home", home), ("away", away)):
        for slot, ent in enumerate(entries, start=1):
            _add(MatchParticipant(match_id=m.id, side=side, slot=slot, role="member", entry_id=ent.id, player_id=ent.player_id))
    for n, (h, a) in enumerate(sets, start=1):
        _add(MatchSet(match_id=m.id, set_no=n, home_games=h, away_games=a))
    return m
