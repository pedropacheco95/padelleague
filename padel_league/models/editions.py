from padel_league import model
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , String , Table, ForeignKey , Boolean, Date
from sqlalchemy.orm import relationship

class Edition(db.Model ,model.Model , model.Base):
    __tablename__ = 'editions'
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True)
    name = Column(String(80), unique=True, nullable=False)
    league_id = Column(Integer, ForeignKey('leagues.id'))

    league = relationship('League', back_populates="editions")
    divisions = relationship('Division', back_populates="edition")

    players_relations_registrations = relationship('Registration', back_populates='edition')

    def has_ended(self):
        return all([division.has_ended for division in self.divisions])
    
    def is_open_division(self):
        return all([division.open_division for division in self.divisions])