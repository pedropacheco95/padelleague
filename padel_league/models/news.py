
from email.policy import default
from multiprocessing.heap import Arena
from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , String , Text, ForeignKey
from sqlalchemy.orm import relationship
import re

class News(db.Model ,model.Model, model.Base):
    __tablename__ = 'news'
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True)
    title = Column(String(80), unique=True, nullable=False)
    cover_path = Column(String(80), default='default_news.jpg')
    author = Column(String(80))
    text = Column(Text, nullable=False)

