from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from padel_league import model
from padel_league.sql_db import db
from padel_league.tools.input_tools import Block, Field, Form


class Registration(db.Model, model.Model):
    __tablename__ = "registrations"
    __table_args__ = {"extend_existing": True}
    page_title = "Registos"
    model_name = "Registration"

    player_id = Column(Integer, ForeignKey("players.id"), primary_key=True)
    edition_id = Column(Integer, ForeignKey("editions.id"), primary_key=True)

    edition = relationship("Edition", back_populates="players_relations_registrations")
    player = relationship("Player", back_populates="editions_relations_registrations")

    def display_all_info(self):
        searchable_column = {"field": "player", "label": "Jogador"}
        table_columns = [
            searchable_column,
            {"field": "edition", "label": "Edição"},
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
                name="edition",
                label="Edição",
                type="ManyToOne",
                required=True,
                related_model="Edition",
            ),
        ]
        info_block = Block("info_block", fields)
        form.add_block(info_block)
        return form
