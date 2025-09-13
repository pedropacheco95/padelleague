from sqlalchemy import Column, Date, Integer, String
from sqlalchemy.ext.hybrid import hybrid_property

from padel_league import model
from padel_league.sql_db import db


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
