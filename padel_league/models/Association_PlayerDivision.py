from sqlalchemy import Column, Float, ForeignKey, Integer
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from padel_league import model
from padel_league.sql_db import db
from padel_league.tools.input_tools import Block, Field, Form


class Association_PlayerDivision(db.Model, model.Model):
    __tablename__ = "players_in_division"
    __table_args__ = {"extend_existing": True}
    page_title = "Relação de Jogador Divisao"
    model_name = "Association_PlayerDivision"

    id = Column(Integer, primary_key=True, autoincrement=True)

    player_id = Column(Integer, ForeignKey("players.id"), primary_key=True)
    division_id = Column(Integer, ForeignKey("divisions.id"), primary_key=True)

    division = relationship("Division", back_populates="players_relations")
    player = relationship("Player", back_populates="division_relations")

    @hybrid_property
    def name(self):
        return f"{self.player} in {self.division}"

    place = Column(Integer)
    points = Column(Float, default=0)
    appearances = Column(Integer, default=0)
    percentage_of_appearances = Column(Float, default=0)
    wins = Column(Integer, default=0)
    draws = Column(Integer, default=0)
    losts = Column(Integer, default=0)
    games_won = Column(Integer, default=0)
    games_lost = Column(Integer, default=0)
    matchweek = Column(Integer, default=0)

    division = relationship("Division", back_populates="players_relations")
    player = relationship("Player", back_populates="divisions_relations")

    def compute_ranking_points(self):
        if not self.division.has_ended:
            return 0
        division = self.division
        # Add base points if the division qualifies:
        # For closed divisions or open divisions with more than 20 matches.
        if division.has_ended and (not division.open_division):
            decay_factor = 0.75 ** (self.place - 1)
            total_points = int(division.rating * decay_factor)

        # Bonus points for wins and draws in the division.
        wins = len(self.player.matches_won(division=division))
        draws = len(self.player.matches_drawn(division=division))
        total_points += wins * (division.rating / 100)
        total_points += draws * (division.rating / 250)
        return total_points

    def display_all_info(self):
        searchable_column = {"field": "player", "label": "Jogador"}
        table_columns = [
            {"field": "division", "label": "Divisão"},
            searchable_column,
            {"field": "place", "label": "Lugar"},
            {"field": "points", "label": "Pontos"},
            {"field": "appearances", "label": "Presenças"},
            {"field": "percentage_of_appearances", "label": "% Presenças"},
            {"field": "wins", "label": "Vitórias"},
            {"field": "draws", "label": "Empates"},
            {"field": "losts", "label": "Derrotas"},
            {"field": "games_won", "label": "Jogos ganhos"},
            {"field": "games_lost", "label": "Jogos perdidos"},
            {"field": "matchweek", "label": "Jornada"},
        ]
        return searchable_column, table_columns

    def get_create_form(self):
        def get_field(
            name, label, type, required=False, related_model=None, options=None
        ):
            return Field(
                instance_id=self.id,
                model=self.model_name,
                name=name,
                label=label,
                type=type,
                required=required,
                related_model=related_model,
                options=options,
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
                name="division",
                label="Divisão",
                type="ManyToOne",
                required=True,
                related_model="Division",
            ),
            get_field(name="place", label="Lugar", type="Integer"),
            get_field(name="points", label="Pontos", type="Float"),
            get_field(name="appearances", label="Presenças", type="Integer"),
            get_field(
                name="percentage_of_appearances", label="% Presenças", type="Float"
            ),
            get_field(name="wins", label="Vitórias", type="Integer"),
            get_field(name="draws", label="Empates", type="Integer"),
            get_field(name="losts", label="Derrotas", type="Integer"),
            get_field(name="games_won", label="Jogos ganhos", type="Integer"),
            get_field(name="games_lost", label="Jogos perdidos", type="Integer"),
            get_field(name="matchweek", label="Jornada", type="Integer"),
        ]
        info_block = Block("info_block", fields)
        form.add_block(info_block)

        return form
