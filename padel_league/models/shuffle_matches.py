from sqlalchemy import Boolean, Column, ForeignKey, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from padel_league import model
from padel_league.sql_db import db


class ShuffleMatch(db.Model, model.Model):
    __tablename__ = "shuffle_matches"
    __table_args__ = {"extend_existing": True}
    page_title = "Shuffle Matches"
    model_name = "ShuffleMatch"

    id = Column(Integer, primary_key=True, autoincrement=True)
    shuffle_tournament_id = Column(
        Integer, ForeignKey("shuffle_tournaments.id"), nullable=False
    )
    matchweek = Column(Integer, nullable=False)
    division = Column(Integer, nullable=False)
    score1 = Column(Integer)
    score2 = Column(Integer)
    played = Column(Boolean, nullable=False, default=False)

    shuffle_tournament = relationship("ShuffleTournament", back_populates="matches")
    players_relations = relationship(
        "Association_PlayerShuffleMatch", back_populates="shuffle_match"
    )

    def home_players(self):
        return [rel.player for rel in self.players_relations if rel.team == "Home"]

    def away_players(self):
        return [rel.player for rel in self.players_relations if rel.team == "Away"]

    @hybrid_property
    def name(self):
        return f"{self.id} in {self.matchweek} in {self.shuffle_tournament}"
