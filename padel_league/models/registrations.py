from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer, ForeignKey, Float
from sqlalchemy.orm import relationship 

class Registration(db.Model ,model.Model ):
    __tablename__ = 'registrations'
    __table_args__ = {'extend_existing': True}
    page_title = 'Registos'
    model_name = 'Registration'
    
    player_id = Column(Integer, ForeignKey('players.id'), primary_key=True)
    edition_id = Column(Integer, ForeignKey('editions.id'), primary_key=True)

    edition = relationship('Edition', back_populates='players_relations_registrations')
    player = relationship('Player', back_populates='editions_relations_registrations')
