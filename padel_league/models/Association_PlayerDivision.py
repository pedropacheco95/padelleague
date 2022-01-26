from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer, ForeignKey, Float
from sqlalchemy.orm import relationship 

class Association_PlayerDivision(db.Model ,model.Model, model.Base):
    __tablename__ = 'players_in_division'
    __table_args__ = {'extend_existing': True}
    player_id = Column(Integer, ForeignKey('players.id'), primary_key=True)
    division_id = Column(Integer, ForeignKey('divisions.id'), primary_key=True)

    place = Column(Integer)
    points = Column(Float,default=0)
    appearances = Column(Integer,default=0)
    percentage_of_appearances = Column(Float,default=0)
    wins = Column(Integer,default=0)
    draws = Column(Integer,default=0)
    losts = Column(Integer,default=0)
    games_won = Column(Integer,default=0)
    games_lost = Column(Integer,default=0)
    matchweek = Column(Integer,default=0)

    division = relationship('Division', back_populates='players_relations')
    player = relationship('Player', back_populates='divisions_relations')
