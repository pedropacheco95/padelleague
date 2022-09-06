from datetime import date

from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , String , Text, ForeignKey, Table , Date , Float, Enum
from sqlalchemy.orm import relationship
from flask import session , url_for

class Player(db.Model ,model.Model, model.Base):
    __tablename__ = 'players'
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True)
    name = Column(String(80), unique=True, nullable=False)
    full_name =  Column(Text, unique=True)
    birthday = Column(Date)
    picture_path = Column(String(80), default='default_player.jpg')
    large_picture_path = Column(String(80), default='large_pic_default.jpg')
    ranking_points = Column(Integer, default=0)
    ranking_position = Column(Integer, default=0)
    height = Column(Float,default=1.75)
    prefered_hand = Column(Enum('Direita','Esquerda'),server_default='Direita')
    prefered_position = Column(Enum('Lado direito','Lado esquerdo','Tanto faz'),server_default='Tanto faz')

    user = relationship('User',back_populates='player', uselist=False)
    matches_relations = relationship('Association_PlayerMatch', back_populates='player')
    divisions_relations = relationship('Association_PlayerDivision', back_populates='player')
    editions_relations_registrations = relationship('Registration', back_populates='player')

    #WHEN ADDING A MATCH THIS DICT SHOULD BE RESET TO {}
    match_relations_in_division = {}

    def get_match_relations(self,division = None):
        relations = self.matches_relations
        if division:
            #Tentar fazer isto funcionar. Neste momento o dicionario fica igual para todos e por isso todos ficam com os mesmos pontos
            """ if not division in self.match_relations_in_division.keys():
                self.match_relations_in_division[division] = [relation for relation in self.matches_relations if relation.match.division==division]
            relations = self.match_relations_in_division[division] """
            relations = [relation for relation in self.matches_relations if relation.match.division==division]
        return relations

    def get_match_relations_played(self,division = None):
        relations = self.matches_relations
        if division:
            #Tentar fazer isto funcionar. Neste momento o dicionario fica igual para todos e por isso todos ficam com os mesmos pontos
            """ if not division in self.match_relations_in_division.keys():
                self.match_relations_in_division[division] = [relation for relation in self.matches_relations if relation.match.division==division]
            relations = self.match_relations_in_division[division] """
            relations = [relation for relation in self.matches_relations if relation.match.division==division]
        return [relation for relation in relations if relation.match.played]

    def matches_played(self,division=None):
        relations = self.get_match_relations_played(division)
        return [relation.match for relation in relations]

    def matches_won(self,division=None):
        relations = self.get_match_relations_played(division)
        matches = [relation.match for relation in relations if (relation.team=='Home' and relation.match.winner == 1) or (relation.team=='Away' and relation.match.winner == -1)]
        return matches

    def matches_lost(self,division=None):
        relations = self.get_match_relations_played(division)
        matches = [relation.match for relation in relations if (relation.team=='Home' and relation.match.winner == -1) or (relation.team=='Away' and relation.match.winner == 1)]
        return matches

    def matches_drawn(self,division=None):
        relations = self.get_match_relations_played(division)
        matches = [relation.match for relation in relations if relation.match.winner == 0]
        return matches

    def games_won(self,division=None):
        relations = self.get_match_relations_played(division)
        games_won = [relation.match.games_home_team if relation.team=='Home' else relation.match.games_away_team for relation in relations]
        return sum(games_won)

    def games_lost(self,division=None):
        relations = self.get_match_relations_played(division)
        games_lost = [relation.match.games_home_team if relation.team=='Away' else relation.match.games_away_team for relation in relations]
        return sum(games_lost)

    def previous_player(self,division = None):
        if not division:
            division = self.divisions_relations[-1].division
        player_position = division.player_position(self)
        return division.player_in_position(player_position-1)
    
    def next_player(self,division = None):
        if not division:
            division = self.divisions_relations[-1].division
        player_position = division.player_position(self)
        return division.player_in_position(player_position+1%len(division.players_relations))

    def previous_and_next_player(self,division = None):
        if not division:
            division = self.divisions_relations[-1].division
        player_position = division.player_position(self)
        players = {
            'previous': division.player_in_position(player_position-1),
            'next': division.player_in_position((player_position+1)%len(division.players_relations))
        }
        return players

    def points_by_matchweek(self,division):
        matches_won = self.matches_won(division)
        matches_drawn = self.matches_drawn(division)

        matchweeks_won = [match.matchweek for match in matches_won]
        points_matchweek_wins = {matchweek:3 * matchweeks_won.count(matchweek) for matchweek in set(matchweeks_won)}

        matchweeks_drawn = [match.matchweek for match in matches_drawn]
        points_matchweek_draws = {matchweek:matchweeks_drawn.count(matchweek) for matchweek in set(matchweeks_drawn)}

        points_by_matchweek = {k: points_matchweek_wins.get(k, 0) + points_matchweek_draws.get(k, 0) for k in set(points_matchweek_wins) | set(points_matchweek_draws)}

        missing_matchweeks = {i:0 for i in range(1,division.last_updated_matchweek()) if i not in points_by_matchweek.keys()}

        points_by_matchweek.update(missing_matchweeks)
        points_by_matchweek_sorted = {key: points_by_matchweek[key] for key in sorted(list(points_by_matchweek.keys()))}
        return points_by_matchweek_sorted

    def points_by_matchweek_for_graph(self,division):
        points_by_matchweek = self.points_by_matchweek(division)
        return {'x':list(points_by_matchweek.keys()),'y':list(points_by_matchweek.values())}