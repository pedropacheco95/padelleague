from sqlalchemy import Column, Date, ForeignKey, Integer, String
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from padel_league import model
from padel_league.sql_db import db
from padel_league.tools.input_tools import Block, Field, Form


class Newsletter(db.Model, model.Model):
    __tablename__ = "newsletters"
    __table_args__ = {"extend_existing": True}
    page_title = "Newsletters"
    model_name = "Newsletter"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(120), unique=True, nullable=False)
    date = Column(Date, nullable=False)

    image_id = Column(Integer, ForeignKey("images.id", ondelete="SET NULL"))
    image = relationship("Image", foreign_keys=[image_id])

    @property
    def image_url(self):
        return self.image.url() if self.image else None

    @hybrid_property
    def name(self):
        return f"{self.title}"

    def display_all_info(self):
        searchable_column = {"field": "title", "label": "Título"}
        table_columns = [
            searchable_column,
            {"field": "date", "label": "Data"},
            {"field": "image_url", "label": "Imagem"},
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
            get_field(name="title", label="Título", type="Text", required=True),
            get_field(name="date", label="Data", type="Date", required=True),
            get_field(
                name="image_id",
                label="Imagem",
                type="Picture",
                required=False,
            ),
        ]
        info_block = Block("info_block", fields)
        form.add_block(info_block)
        return form
