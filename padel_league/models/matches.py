from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , Boolean , Text, ForeignKey , DateTime
from sqlalchemy.orm import relationship

class Match(db.Model ,model.Model, model.Base):
    __tablename__ = 'matches'
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True)
    games_home_team = Column(Integer)
    games_away_team = Column(Integer)
    date_hour = Column(DateTime)
    #This variable should be calculated (maybe specify __init__ fucntion)
    winner = Column(Integer)
    matchweek = Column(Integer, nullable=False)
    field = Column(Text)
    played = Column(Boolean,nullable=False)
    division_id =  Column(Integer, ForeignKey('divisions.id'))

    division = relationship('Division', back_populates="matches")
    players_relations = relationship('Association_PlayerMatch', back_populates="match")

    def home_players(self):
        return [rel.player for rel in self.players_relations if rel.team=='Home']
    
    def away_players(self):
        return [rel.player for rel in self.players_relations if rel.team=='Away']

    def name(self):
        home_players = self.home_players()
        away_players = self.away_players()
        home0 = home_players[0].name if home_players else 'Substituto'
        home1 = home_players[1].name if len(home_players) == 2 else 'Substituto'
        away0 = away_players[0].name if away_players else 'Substituto'
        away1 = away_players[1].name if len(away_players) == 2 else 'Substituto'
        return '{player1};{player2} VS {player3};{player4}'.format(player1=home0, player2=home1,player3=away0,player4=away1)
