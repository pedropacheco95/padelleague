from sqlalchemy import Boolean, Column, ForeignKey, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from padel_league import model
from padel_league.sql_db import db
from padel_league.tools.input_tools import Block, Field, Form


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

    def display_all_info(self):
        searchable_column = {"field": "id", "label": "ID"}
        table_columns = [
            searchable_column,
            {"field": "shuffle_tournament", "label": "Torneio"},
            {"field": "matchweek", "label": "Jornada"},
            {"field": "division", "label": "Divisão"},
            {"field": "score1", "label": "Score 1"},
            {"field": "score2", "label": "Score 2"},
            {"field": "played", "label": "Jogado"},
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
                name="shuffle_tournament",
                label="Torneio",
                type="ManyToOne",
                required=True,
                related_model="ShuffleTournament",
            ),
            get_field(
                name="matchweek",
                label="Jornada",
                type="Integer",
                required=True,
            ),
            get_field(
                name="division",
                label="Divisão",
                type="Integer",
                required=True,
            ),
            get_field(name="score1", label="Score 1", type="Integer"),
            get_field(name="score2", label="Score 2", type="Integer"),
            get_field(name="played", label="Jogado", type="Boolean"),
            get_field(
                name="players_relations",
                label="Jogadores (Relações)",
                type="OneToMany",
                related_model="Association_PlayerShuffleMatch",
            ),
        ]
        info_block = Block("info_block", fields)
        form.add_block(info_block)
        return form
