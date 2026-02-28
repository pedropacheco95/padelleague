from sqlalchemy import Column, Date, Integer, String
from sqlalchemy.ext.hybrid import hybrid_property

from padel_league import model
from padel_league.sql_db import db
from padel_league.tools.input_tools import Block, Field, Form


class Video(db.Model, model.Model):
    __tablename__ = "videos"
    __table_args__ = {"extend_existing": True}
    page_title = "Vídeos"
    model_name = "Video"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(120), unique=True, nullable=False)
    date = Column(Date, nullable=False)
    youtube_link = Column(String(255), nullable=False)
    image_path = Column(String(120), default="default_video.jpg")

    @hybrid_property
    def name(self):
        return f"{self.title}"

    def display_all_info(self):
        searchable_column = {"field": "title", "label": "Título"}
        table_columns = [
            searchable_column,
            {"field": "date", "label": "Data"},
            {"field": "youtube_link", "label": "YouTube"},
            {"field": "image_path", "label": "Imagem"},
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
                name="youtube_link",
                label="YouTube",
                type="Text",
                required=True,
            ),
            get_field(name="image_path", label="Imagem", type="Text"),
        ]
        info_block = Block("info_block", fields)
        form.add_block(info_block)
        return form
