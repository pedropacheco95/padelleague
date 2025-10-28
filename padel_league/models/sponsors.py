from flask import url_for
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from padel_league import model
from padel_league.sql_db import db
from padel_league.tools.input_tools import Block, Field, Form


class Sponsor(db.Model, model.Model):
    __tablename__ = "sponsors"
    __table_args__ = {"extend_existing": True}
    page_title = "Patrocinadores"
    model_name = "Sponsor"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), nullable=False, unique=True)
    image = Column(String(200))
    website = Column(String(80), nullable=False, unique=True)

    sponsor_clicks = relationship("SponsorClick", back_populates="sponsor")

    image_id = Column(Integer, ForeignKey("images.id", ondelete="SET NULL"))
    image = relationship("Image", foreign_keys=[image_id])

    @property
    def image_url(self):
        return self.image.url() if self.image else None

    @hybrid_property
    def style(self):
        return f"style=background-color:{self.color}"

    @hybrid_property
    def url(self):
        return url_for("sponsors.sponsor_click", sponsor_id=self.id)

    @hybrid_property
    def image_filename(self):
        return f"images/{self.image}" if self.image else "images/default_app_image.png"

    def display_all_info(self):
        searchable_column = {"field": "name", "label": "Nome"}
        table_columns = [
            {"field": "id", "label": "Numero"},
            searchable_column,
        ]
        return searchable_column, table_columns

    def get_create_form(self):
        def get_field(
            name,
            label,
            type,
            required=False,
            related_model=None,
            options=None,
            value=None,
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
                value=value,
            )

        form = Form()
        # Create Picture block
        fields = [get_field(name="image_id", label="Icone da app", type="Picture")]
        picture_block = Block("picture_block", fields)
        form.add_block(picture_block)

        # Create Info block
        fields = [
            get_field(name="name", label="Nome", type="Text", required=True),
            get_field(name="website", label="Website", type="Text", required=True),
        ]
        info_block = Block("info_block", fields)
        form.add_block(info_block)

        return form
