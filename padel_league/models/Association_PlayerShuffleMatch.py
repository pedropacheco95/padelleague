from sqlalchemy import Column, Enum, ForeignKey, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from padel_league import model
from padel_league.sql_db import db


class Association_PlayerShuffleMatch(db.Model, model.Model):
    __tablename__ = "players_in_shuffle_match"
    __table_args__ = {"extend_existing": True}
    page_title = "Relação Jogador Shuffle Match"
    model_name = "Association_PlayerShuffleMatch"

    id = Column(Integer, primary_key=True, autoincrement=True)

    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    shuffle_match_id = Column(Integer, ForeignKey("shuffle_matches.id"), nullable=False)
    team = Column(Enum("Home", "Away", name="shuffle_teams"), nullable=False)

    player = relationship("Player", back_populates="shuffle_matches_relations")
    shuffle_match = relationship("ShuffleMatch", back_populates="players_relations")

    @hybrid_property
    def name(self):
        return f"{self.player} in {self.shuffle_match}"
