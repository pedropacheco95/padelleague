from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from padel_league import model
from padel_league.sql_db import db


class Association_PlayerShuffleTournament(db.Model, model.Model):
    __tablename__ = "players_in_shuffle_tournament"
    __table_args__ = {"extend_existing": True}
    page_title = "Relação Jogador Shuffle Tournament"
    model_name = "Association_PlayerShuffleTournament"

    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    shuffle_tournament_id = Column(
        Integer, ForeignKey("shuffle_tournaments.id"), nullable=False
    )

    division_number = Column(Integer, nullable=False)
    position = Column(Integer, default=0)
    points = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    draws = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    games_played = Column(Integer, default=0)
    games_won = Column(Integer, default=0)
    games_lost = Column(Integer, default=0)

    player = relationship("Player", back_populates="shuffle_tournaments_relations")
    shuffle_tournament = relationship(
        "ShuffleTournament", back_populates="players_relations"
    )

    @hybrid_property
    def name(self):
        return f"{self.player} in {self.shuffle_tournament}"
