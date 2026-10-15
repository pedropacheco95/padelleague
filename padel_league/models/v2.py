"""v2 competition model.

league → season → competition (instance of an event slot) → stage → group,
with rounds, entries, group members, pairs, matches, sets, participants,
absences, awards and ranking snapshots. Schema: migrations/sql/v2_core.sql.

The pre-v2 classes (Division, Match, Association_PlayerDivision, ...) map
onto read-only views in schema `compat` until every caller uses these.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from padel_league.sql_db import db

FORMATS = ("classica", "shuffle", "teams", "super_cup")
STATUSES = ("planned", "running", "ended")


class RankingRule(db.Model):
    __tablename__ = "ranking_rules"

    id = Column(Integer, primary_key=True)
    key = Column(Text, nullable=False, unique=True)
    name = Column(Text, nullable=False)
    mode = Column(Text, nullable=False)
    last_n = Column(Integer)
    decay = Column(Float, nullable=False, default=0.75)
    win_bonus_divisor = Column(Float, nullable=False, default=100)
    draw_bonus_divisor = Column(Float, nullable=False, default=250)
    options = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Season(db.Model):
    __tablename__ = "seasons"
    __table_args__ = (UniqueConstraint("league_id", "name"),)

    id = Column(Integer, primary_key=True)
    league_id = Column(BigInteger, ForeignKey("leagues.id"), nullable=False)
    name = Column(Text, nullable=False)
    starts_on = Column(Date)
    ends_on = Column(Date)
    ranking_rule_id = Column(Integer, ForeignKey("ranking_rules.id"))

    ranking_rule = relationship("RankingRule")
    competitions = relationship("Competition", back_populates="season", order_by="Competition.starts_on")


class EventSlot(db.Model):
    """The stable identity of a recurring event ("Clássica I"), across seasons."""

    __tablename__ = "event_slots"

    id = Column(Integer, primary_key=True)
    league_id = Column(BigInteger, ForeignKey("leagues.id"), nullable=False)
    key = Column(Text, nullable=False, unique=True)
    name = Column(Text, nullable=False)
    format = Column(Text, nullable=False)
    holds_ranking_slot = Column(Boolean)  # None = not decided yet
    calendar_order = Column(Integer, nullable=False)


class Competition(db.Model):
    """One instance of a tournament: an old edition, a shuffle, a Teams edition."""

    __tablename__ = "competitions"
    __table_args__ = (CheckConstraint(f"format IN {FORMATS}"),)

    id = Column(BigInteger, primary_key=True)
    season_id = Column(Integer, ForeignKey("seasons.id"), nullable=False)
    event_slot_id = Column(Integer, ForeignKey("event_slots.id"))
    name = Column(Text)
    format = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="planned")
    starts_on = Column(Date)
    ends_on = Column(Date)
    rules = Column(JSONB, nullable=False, default=dict)
    counts_for_attendance = Column(Boolean, nullable=False, default=True)
    legacy_shuffle_id = Column(Integer, unique=True)
    title = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    season = relationship("Season", back_populates="competitions")
    event_slot = relationship("EventSlot")
    stages = relationship("Stage", back_populates="competition", order_by="Stage.number", cascade="all, delete-orphan")
    entries = relationship("Entry", back_populates="competition", cascade="all, delete-orphan")


class Stage(db.Model):
    """A period during which the groups stay fixed (a Teams mini-tournament, a shuffle week)."""

    __tablename__ = "stages"
    __table_args__ = (UniqueConstraint("competition_id", "number"),)

    id = Column(Integer, primary_key=True)
    competition_id = Column(BigInteger, ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False)
    number = Column(Integer, nullable=False)
    name = Column(Text)
    seeding_method = Column(Text)
    seeded_from_id = Column(Integer, ForeignKey("ranking_snapshots.id"))
    emits_award = Column(Boolean, nullable=False, default=False)
    status = Column(Text, nullable=False, default="planned")
    # Teams: partner choices are accepted until this moment (UTC); closing pairs the rest.
    pairing_deadline = Column(DateTime)
    pairing_closed = Column(Boolean, nullable=False, default=False)

    competition = relationship("Competition", back_populates="stages")
    groups = relationship("CompetitionGroup", back_populates="stage", order_by="CompetitionGroup.tier", cascade="all, delete-orphan")
    rounds = relationship("Round", back_populates="stage", order_by="Round.number", cascade="all, delete-orphan")
    pairs = relationship("Pair", back_populates="stage", cascade="all, delete-orphan")
    seeded_from = relationship("RankingSnapshot")


class CompetitionGroup(db.Model):
    """A division, a cup, or a shuffle division within one stage."""

    __tablename__ = "competition_groups"

    id = Column(BigInteger, primary_key=True)
    stage_id = Column(Integer, ForeignKey("stages.id", ondelete="CASCADE"), nullable=False)
    tier = Column(Integer)
    name = Column(Text)
    structure = Column(Text, nullable=False, default="round_robin")
    rating = Column(BigInteger)
    multiplier = Column(Integer)
    starts_at = Column(DateTime)
    end_date = Column(DateTime)
    has_ended = Column(Boolean)
    open_division = Column(Boolean)
    standings_up_to_date = Column(Boolean)
    logo_image_id = Column(Integer, ForeignKey("images.id", ondelete="SET NULL"))
    large_picture_id = Column(Integer, ForeignKey("images.id", ondelete="SET NULL"))

    stage = relationship("Stage", back_populates="groups")
    members = relationship("GroupMember", back_populates="group", order_by="GroupMember.id", cascade="all, delete-orphan")
    matches = relationship("CompetitionMatch", back_populates="group", order_by="CompetitionMatch.id")


class Round(db.Model):
    __tablename__ = "rounds"
    __table_args__ = (UniqueConstraint("stage_id", "number"),)

    id = Column(Integer, primary_key=True)
    stage_id = Column(Integer, ForeignKey("stages.id", ondelete="CASCADE"), nullable=False)
    number = Column(Integer, nullable=False)
    date = Column(Date)

    stage = relationship("Stage", back_populates="rounds")


class Entry(db.Model):
    """A player's place in one competition."""

    __tablename__ = "entries"
    __table_args__ = (UniqueConstraint("competition_id", "player_id"),)

    id = Column(Integer, primary_key=True)
    competition_id = Column(BigInteger, ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False)
    player_id = Column(BigInteger, ForeignKey("players.id"), nullable=False)
    kind = Column(Text, nullable=False, default="regular")
    status = Column(Text, nullable=False, default="active")
    seed = Column(Integer)
    final_place = Column(Integer)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    competition = relationship("Competition", back_populates="entries")
    player = relationship("Player")


class Pair(db.Model):
    """Two entries playing together for one stage. entry_a_id < entry_b_id."""

    __tablename__ = "pairs"
    __table_args__ = (
        UniqueConstraint("stage_id", "entry_a_id"),
        UniqueConstraint("stage_id", "entry_b_id"),
    )

    id = Column(Integer, primary_key=True)
    stage_id = Column(Integer, ForeignKey("stages.id", ondelete="CASCADE"), nullable=False)
    entry_a_id = Column(Integer, ForeignKey("entries.id"), nullable=False)
    entry_b_id = Column(Integer, ForeignKey("entries.id"), nullable=False)
    # mutual | ranking | draw | rotation | manual
    formed_by = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    @property
    def entry_ids(self):
        return (self.entry_a_id, self.entry_b_id)

    stage = relationship("Stage", back_populates="pairs")
    entry_a = relationship("Entry", foreign_keys=[entry_a_id])
    entry_b = relationship("Entry", foreign_keys=[entry_b_id])


class PartnerRequest(db.Model):
    __tablename__ = "partner_requests"
    __table_args__ = (UniqueConstraint("stage_id", "from_entry_id"),)

    id = Column(Integer, primary_key=True)
    stage_id = Column(Integer, ForeignKey("stages.id", ondelete="CASCADE"), nullable=False)
    from_entry_id = Column(Integer, ForeignKey("entries.id"), nullable=False)
    to_entry_id = Column(Integer, ForeignKey("entries.id"), nullable=False)
    submitted_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class GroupMember(db.Model):
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "entry_id"),)

    id = Column(BigInteger, primary_key=True)
    group_id = Column(BigInteger, ForeignKey("competition_groups.id", ondelete="CASCADE"), nullable=False)
    entry_id = Column(Integer, ForeignKey("entries.id", ondelete="CASCADE"), nullable=False)
    seed = Column(Integer)
    pair_id = Column(Integer, ForeignKey("pairs.id"))

    group = relationship("CompetitionGroup", back_populates="members")
    entry = relationship("Entry")
    pair = relationship("Pair")
    snapshot = relationship("StandingSnapshot", uselist=False, back_populates="group_member")


class StandingSnapshot(db.Model):
    """The stored standings row of a finished group, kept exactly as shown."""

    __tablename__ = "standing_snapshots"

    id = Column(BigInteger, primary_key=True)
    entry_id = Column(Integer, ForeignKey("entries.id", ondelete="CASCADE"), nullable=False)
    group_member_id = Column(BigInteger, ForeignKey("group_members.id", ondelete="CASCADE"), unique=True)
    place = Column(Integer)
    points = Column(Float)
    appearances = Column(BigInteger)
    percentage_of_appearances = Column(Float)
    wins = Column(BigInteger)
    draws = Column(BigInteger)
    losses = Column(BigInteger)
    games_played = Column(BigInteger)
    games_won = Column(BigInteger)
    games_lost = Column(BigInteger)
    matchweek = Column(BigInteger)
    next_division = Column(Integer)
    legacy_id = Column(Integer)
    source = Column(Text, nullable=False, default="legacy")

    group_member = relationship("GroupMember", back_populates="snapshot")
    entry = relationship("Entry")


class CompetitionMatch(db.Model):
    __tablename__ = "matches"

    id = Column(BigInteger, primary_key=True)
    group_id = Column(BigInteger, ForeignKey("competition_groups.id", ondelete="CASCADE"), nullable=False)
    round_id = Column(Integer, ForeignKey("rounds.id"), nullable=False)
    scheduled_at = Column(DateTime)
    court = Column(Text)
    status = Column(Text, nullable=False, default="scheduled")
    # home | away for a walkover (no sets stored); null otherwise.
    walkover_winner = Column(Text)
    home_pair_id = Column(Integer, ForeignKey("pairs.id"))
    away_pair_id = Column(Integer, ForeignKey("pairs.id"))
    bracket_code = Column(Text)
    winner_to_match_id = Column(BigInteger, ForeignKey("matches.id"))
    loser_to_match_id = Column(BigInteger, ForeignKey("matches.id"))
    legacy_shuffle_match_id = Column(Integer, unique=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by_user_id = Column(BigInteger)

    group = relationship("CompetitionGroup", back_populates="matches")
    round = relationship("Round")
    sets = relationship("MatchSet", back_populates="match", order_by="MatchSet.set_no", cascade="all, delete-orphan")
    participants = relationship(
        "MatchParticipant", back_populates="match", order_by="MatchParticipant.id", cascade="all, delete-orphan"
    )
    home_pair = relationship("Pair", foreign_keys=[home_pair_id])
    away_pair = relationship("Pair", foreign_keys=[away_pair_id])

    @property
    def played(self):
        return self.status == "played"

    def set_score(self, home_games, away_games, set_no=1):
        existing = next((s for s in self.sets if s.set_no == set_no), None)
        if existing is None:
            self.sets.append(MatchSet(set_no=set_no, home_games=home_games, away_games=away_games))
        else:
            existing.home_games, existing.away_games = home_games, away_games


class MatchSet(db.Model):
    __tablename__ = "match_sets"

    match_id = Column(BigInteger, ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True)
    set_no = Column(SmallInteger, primary_key=True)
    home_games = Column(Integer)
    away_games = Column(Integer)
    outcome = Column(Text, nullable=False, default="completed")

    match = relationship("CompetitionMatch", back_populates="sets")


class MatchParticipant(db.Model):
    """A known occupant of a slot. No row for a slot means "unknown" (Substituto)."""

    __tablename__ = "match_participants"
    __table_args__ = (
        UniqueConstraint("match_id", "side", "slot"),
        UniqueConstraint("match_id", "player_id"),
    )

    id = Column(BigInteger, primary_key=True)
    match_id = Column(BigInteger, ForeignKey("matches.id", ondelete="CASCADE"), nullable=False)
    side = Column(Text, nullable=False)  # home | away
    slot = Column(SmallInteger, nullable=False)  # 1 | 2
    role = Column(Text, nullable=False)  # member | substitute
    entry_id = Column(Integer, ForeignKey("entries.id"))
    player_id = Column(BigInteger, ForeignKey("players.id"), nullable=False)

    match = relationship("CompetitionMatch", back_populates="participants")
    entry = relationship("Entry")
    player = relationship("Player")


class Absence(db.Model):
    __tablename__ = "absences"
    __table_args__ = (UniqueConstraint("entry_id", "round_id"),)

    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("entries.id", ondelete="CASCADE"), nullable=False)
    round_id = Column(Integer, ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False)
    kind = Column(Text, nullable=False)  # full | partial
    source = Column(Text, nullable=False)  # derived | recorded
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_by_user_id = Column(BigInteger)

    entry = relationship("Entry")
    round = relationship("Round")


class AwardEvent(db.Model):
    """One distribution of ranking points (a classica division ending, a Teams mini-tournament)."""

    __tablename__ = "award_events"

    id = Column(Integer, primary_key=True)
    competition_id = Column(BigInteger, ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False)
    stage_id = Column(Integer, ForeignKey("stages.id"))
    group_id = Column(BigInteger, ForeignKey("competition_groups.id"))
    awarded_at = Column(DateTime)
    source = Column(Text, nullable=False, default="computed")

    competition = relationship("Competition")
    awards = relationship("Award", back_populates="event", cascade="all, delete-orphan")


class Award(db.Model):
    __tablename__ = "awards"
    __table_args__ = (UniqueConstraint("award_event_id", "entry_id"),)

    id = Column(Integer, primary_key=True)
    award_event_id = Column(Integer, ForeignKey("award_events.id", ondelete="CASCADE"), nullable=False)
    entry_id = Column(Integer, ForeignKey("entries.id", ondelete="CASCADE"), nullable=False)
    player_id = Column(BigInteger, ForeignKey("players.id"), nullable=False)
    group_id = Column(BigInteger, ForeignKey("competition_groups.id"))
    place = Column(Integer)
    rating = Column(BigInteger)
    place_points = Column(Float, nullable=False, default=0)
    bonus_points = Column(Float, nullable=False, default=0)
    wins = Column(Integer, nullable=False, default=0)
    draws = Column(Integer, nullable=False, default=0)

    event = relationship("AwardEvent", back_populates="awards")

    @property
    def total(self):
        return self.place_points + self.bonus_points


class RankingSnapshot(db.Model):
    __tablename__ = "ranking_snapshots"

    id = Column(Integer, primary_key=True)
    league_id = Column(BigInteger, ForeignKey("leagues.id"), nullable=False)
    rule_id = Column(Integer, ForeignKey("ranking_rules.id"), nullable=False)
    after_award_event_id = Column(Integer, ForeignKey("award_events.id"))
    computed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    is_dry_run = Column(Boolean, nullable=False, default=False)
    note = Column(Text)

    rule = relationship("RankingRule")
    entries = relationship("RankingEntry", back_populates="snapshot", cascade="all, delete-orphan")


class RankingEntry(db.Model):
    __tablename__ = "ranking_entries"

    snapshot_id = Column(Integer, ForeignKey("ranking_snapshots.id", ondelete="CASCADE"), primary_key=True)
    player_id = Column(BigInteger, ForeignKey("players.id"), primary_key=True)
    points = Column(Float, nullable=False)
    position = Column(Integer)

    snapshot = relationship("RankingSnapshot", back_populates="entries")
    player = relationship("Player")


class RankingSlotValue(db.Model):
    __tablename__ = "ranking_slot_values"

    snapshot_id = Column(Integer, ForeignKey("ranking_snapshots.id", ondelete="CASCADE"), primary_key=True)
    player_id = Column(BigInteger, ForeignKey("players.id"), primary_key=True)
    competition_id = Column(BigInteger, ForeignKey("competitions.id"), primary_key=True)
    points = Column(Float, nullable=False)
    source = Column(Text, nullable=False, default="scored")


class GoldenTicket(db.Model):
    __tablename__ = "golden_tickets"

    id = Column(Integer, primary_key=True)
    player_id = Column(BigInteger, ForeignKey("players.id"), nullable=False)
    level = Column(Integer, nullable=False)
    source_competition_id = Column(BigInteger, ForeignKey("competitions.id"))
    earned_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    status = Column(Text, nullable=False, default="pending")
    expires_at = Column(DateTime)


class Vacancy(db.Model):
    __tablename__ = "vacancies"

    id = Column(Integer, primary_key=True)
    competition_id = Column(BigInteger, ForeignKey("competitions.id"), nullable=False)
    tier = Column(Integer, nullable=False)
    opened_by_entry_id = Column(Integer, ForeignKey("entries.id"))
    opened_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    filled_by = Column(Text)
    golden_ticket_id = Column(Integer, ForeignKey("golden_tickets.id"))
    filled_entry_id = Column(Integer, ForeignKey("entries.id"))


class AuditEvent(db.Model):
    __tablename__ = "audit_events"

    id = Column(BigInteger, primary_key=True)
    actor_user_id = Column(BigInteger)
    entity = Column(Text, nullable=False)
    entity_id = Column(BigInteger)
    action = Column(Text, nullable=False)
    before = Column(JSONB)
    after = Column(JSONB)
    at = Column(DateTime, nullable=False, default=datetime.utcnow)
