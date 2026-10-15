"""PPL Teams: roster, mini-tournaments and partner choice.

Only what pair formation needs. Results and standings for Teams arrive with
the v2 data model, which absorbs these tables (partner_requests, pairs).
"""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from padel_league.sql_db import db


class TeamsPlayer(db.Model):
    """A player taking part in the Teams edition."""

    __tablename__ = "teams_players"

    player_id = Column(Integer, ForeignKey("players.id", ondelete="CASCADE"), primary_key=True)
    player = relationship("Player")


class TeamsMiniTournament(db.Model):
    __tablename__ = "teams_mini_tournaments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    number = Column(Integer, nullable=False, unique=True)
    # Partner choices are accepted until this moment (stored in UTC).
    pairing_deadline = Column(DateTime, nullable=False)
    pairing_closed = Column(Boolean, nullable=False, default=False)


class TeamsPartnerRequest(db.Model):
    """One player's declared partner for a mini-tournament. Counts only if mutual."""

    __tablename__ = "teams_partner_requests"
    __table_args__ = (
        UniqueConstraint("mini_tournament_id", "player_id"),
        CheckConstraint("player_id <> partner_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    mini_tournament_id = Column(Integer, ForeignKey("teams_mini_tournaments.id", ondelete="CASCADE"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    partner_id = Column(Integer, ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TeamsPair(db.Model):
    """A formed pair. player_a_id < player_b_id, so each pair has one spelling."""

    __tablename__ = "teams_pairs"
    __table_args__ = (
        UniqueConstraint("mini_tournament_id", "player_a_id"),
        UniqueConstraint("mini_tournament_id", "player_b_id"),
        CheckConstraint("player_a_id < player_b_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    mini_tournament_id = Column(Integer, ForeignKey("teams_mini_tournaments.id", ondelete="CASCADE"), nullable=False)
    player_a_id = Column(Integer, ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    player_b_id = Column(Integer, ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    # mutual: both declared each other; auto: paired by ranking at close; admin: set by hand.
    source = Column(String(16), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    player_a = relationship("Player", foreign_keys=[player_a_id])
    player_b = relationship("Player", foreign_keys=[player_b_id])

    @property
    def player_ids(self):
        return (self.player_a_id, self.player_b_id)
