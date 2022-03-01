from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , String , Text , ForeignKey
from sqlalchemy.orm import relationship

class User(db.Model ,model.Model,model.Base):
    __tablename__ = 'users'
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    password = Column(Text, nullable=False)
    player_id = Column(Integer, ForeignKey('players.id'))

    player = relationship('Player', back_populates="user")