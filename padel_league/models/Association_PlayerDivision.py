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
    
    def compute_ranking_points(self):
        if not self.division.has_ended:
            return 0
        division = self.division
        # Add base points if the division qualifies:
        # For closed divisions or open divisions with more than 20 matches.
        if division.has_ended and (not division.open_division):
            decay_factor = 0.75 ** (self.place - 1)
            total_points = int(division.rating * decay_factor)
        
        # Bonus points for wins and draws in the division.
        wins = len(self.player.matches_won(division=division))
        draws = len(self.player.matches_drawn(division=division))
        total_points += wins * (division.rating / 100)
        total_points += draws * (division.rating / 250)
        return total_points