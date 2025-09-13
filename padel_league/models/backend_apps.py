from flask import url_for
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from padel_league import model
from padel_league.sql_db import db
from padel_league.tools.input_tools import Block, Field, Form


class Backend_App(db.Model, model.Model):
    __tablename__ = "backend_app"
    __table_args__ = {"extend_existing": True}
    page_title = "Aplicações de backend"
    model_name = "Backend_App"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), nullable=False, unique=True)
    app_model_name = Column(String(80), nullable=False, unique=True)
    color = Column(String(10))

    image_id = Column(Integer, ForeignKey("images.id", ondelete="SET NULL"))
    image = relationship("Image", foreign_keys=[image_id])

    @hybrid_property
    def style(self):
        return f"style=background-color:{self.color}"

    @hybrid_property
    def url(self):
        try:
            return url_for("editor.display_all", model=self.app_model_name)
        except Exception:
            return "/editor/display"

    @property
    def image_object_key(self):
        return (
            self.image.object_key
            if self.image
            else "images/Backend_App/default_app_image.png"
        )

    @property
    def image_url(self):
        return self.image.url() if self.image else None

    def display_all_info(self):
        searchable_column = {"field": "name", "label": "Nome"}
        table_columns = [
            {"field": "id", "label": "Numero"},
            searchable_column,
            {"field": "app_image", "label": "App Image"},
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
            get_field(
                name="app_model_name",
                label="Nome do modelo",
                type="Select",
                required=True,
                options=self.get_model_names(),
            ),
            get_field(name="name", label="Nome", type="Text", required=True),
            get_field(name="color", label="Cor", type="Color", required=True),
        ]
        info_block = Block("info_block", fields)
        form.add_block(info_block)

        return form
