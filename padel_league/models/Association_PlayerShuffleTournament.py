from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from padel_league import model
from padel_league.sql_db import db
from padel_league.tools.input_tools import Block, Field, Form


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

    def display_all_info(self):
        searchable_column = {"field": "player", "label": "Jogador"}
        table_columns = [
            {"field": "shuffle_tournament", "label": "Torneio"},
            searchable_column,
            {"field": "division_number", "label": "Divisão"},
            {"field": "position", "label": "Posição"},
            {"field": "points", "label": "Pontos"},
            {"field": "wins", "label": "Vitórias"},
            {"field": "draws", "label": "Empates"},
            {"field": "losses", "label": "Derrotas"},
            {"field": "games_played", "label": "Jogos"},
            {"field": "games_won", "label": "Games ganhos"},
            {"field": "games_lost", "label": "Games perdidos"},
        ]
        return searchable_column, table_columns

    def get_create_form(self):
        def get_field(name, label, type, required=False, related_model=None):
            return Field(
                instance_id=getattr(self, "id", None),
                model=self.model_name,
                name=name,
                label=label,
                type=type,
                required=required,
                related_model=related_model,
            )

        form = Form()
        fields = [
            get_field(
                name="player",
                label="Jogador",
                type="ManyToOne",
                required=True,
                related_model="Player",
            ),
            get_field(
                name="shuffle_tournament",
                label="Torneio",
                type="ManyToOne",
                required=True,
                related_model="ShuffleTournament",
            ),
            get_field(
                name="division_number",
                label="Divisão",
                type="Integer",
                required=True,
            ),
            get_field(name="position", label="Posição", type="Integer"),
            get_field(name="points", label="Pontos", type="Integer"),
            get_field(name="wins", label="Vitórias", type="Integer"),
            get_field(name="draws", label="Empates", type="Integer"),
            get_field(name="losses", label="Derrotas", type="Integer"),
            get_field(name="games_played", label="Jogos", type="Integer"),
            get_field(name="games_won", label="Games ganhos", type="Integer"),
            get_field(name="games_lost", label="Games perdidos", type="Integer"),
        ]
        info_block = Block("info_block", fields)
        form.add_block(info_block)
        return form
