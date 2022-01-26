from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer, ForeignKey, Enum 
from sqlalchemy.orm import relationship 

class Association_PlayerMatch(db.Model ,model.Model, model.Base):
    __tablename__ = 'players_in_match'
    __table_args__ = {'extend_existing': True}
    player_id = Column(Integer, ForeignKey('players.id'), primary_key=True)
    match_id = Column(Integer, ForeignKey('matches.id'), primary_key=True)
    team = Column(Enum('Home','Away',name='teams'), primary_key=True)

    match = relationship('Match', back_populates='players_relations')
    player = relationship('Player', back_populates='matches_relations')
