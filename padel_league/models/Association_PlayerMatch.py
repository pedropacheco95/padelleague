from sqlalchemy import Column, Enum, ForeignKey, Integer
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from padel_league import model
from padel_league.sql_db import db
from padel_league.tools.input_tools import Block, Field, Form


class Association_PlayerMatch(db.Model, model.Model):
    __tablename__ = "players_in_match"
    __table_args__ = {"extend_existing": True}
    page_title = "Relação de Jogador Jogo"
    model_name = "Association_PlayerMatch"

    id = Column(Integer, primary_key=True, autoincrement=True)

    player_id = Column(Integer, ForeignKey("players.id"), primary_key=True)
    match_id = Column(Integer, ForeignKey("matches.id"), primary_key=True)
    team = Column(Enum("Home", "Away", name="teams"), primary_key=True)

    match = relationship("Match", back_populates="players_relations")
    player = relationship("Player", back_populates="matches_relations")

    sort_order = "newest"

    @hybrid_property
    def name(self):
        return f"{self.player} in {self.match}"

    def display_all_info(self):
        searchable_column = {"field": "player", "label": "Jogador"}
        table_columns = [
            {"field": "match", "label": "Jogo"},
            searchable_column,
            {"field": "team", "label": "Equipa"},
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

        # Info block
        fields = [
            get_field(
                name="player",
                label="Jogador",
                type="ManyToOne",
                required=True,
                related_model="Player",
            ),
            get_field(
                name="match",
                label="Jogo",
                type="ManyToOne",
                required=True,
                related_model="Match",
            ),
            get_field(
                name="team",
                label="Equipa",
                type="Select",
                required=True,
                options=["Home", "Away"],
            ),
        ]
        info_block = Block("info_block", fields)
        form.add_block(info_block)

        return form
