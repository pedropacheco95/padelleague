from sqlalchemy import Column, Enum, ForeignKey, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from padel_league import model
from padel_league.sql_db import db
from padel_league.tools.input_tools import Block, Field, Form


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

    def display_all_info(self):
        searchable_column = {"field": "player", "label": "Jogador"}
        table_columns = [
            {"field": "shuffle_match", "label": "Shuffle Match"},
            searchable_column,
            {"field": "team", "label": "Equipa"},
        ]
        return searchable_column, table_columns

    def get_create_form(self):
        def get_field(
            name, label, type, required=False, related_model=None, options=None
        ):
            return Field(
                instance_id=getattr(self, "id", None),
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
                name="shuffle_match",
                label="Shuffle Match",
                type="ManyToOne",
                required=True,
                related_model="ShuffleMatch",
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
