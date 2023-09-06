from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , String , Text, ForeignKey
from sqlalchemy.orm import relationship

class League(db.Model ,model.Model, model.Base):
    __tablename__ = 'leagues'
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True)
    name = Column(String(80), unique=True, nullable=False)
    
    editions = relationship('Edition', back_populates="league")

    def all_players_that_played(self):
        players = []
        for edition in self.editions:
            for division in edition.divisions:
                players_in_division = [relation.player for relation in division.players_relations]
                players += players_in_division
        return players

    def players_rankings_position(self,update_places=False):
        players = list(set(self.all_players_that_played()))
        if any(player.ranking_position == 0 for player in players):
            self.update_rankings()
        players.sort(key=lambda x: x.ranking_points, reverse=True)
        if update_places:
            for index,player in enumerate(players):
                player.ranking_position = index + 1
                player.save()
        return players

    def update_rankings(self):
        for player in self.all_players_that_played():
            player.ranking_points = 0
            ranking_points_non_average = 0
            divisions_played = [div for div in player.divisions_relations if div.division.has_ended]
            n_divisions_played = len(divisions_played) - 1 if divisions_played else 1 
            for division_relation in player.divisions_relations:
                division = division_relation.division
                if division.has_ended and not division.open_division or division.open_division and len(division.matches) > 20:
                    ranking_points_non_average += int((division.rating)/(2**(division_relation.place - 1)))
                ranking_points_non_average += len(player.matches_won(division=division)) * division.rating/100
                ranking_points_non_average += len(player.matches_drawn(division=division)) * division.rating/250
                player.ranking_position = 1
            player.ranking_points = ranking_points_non_average/n_divisions_played
            player.save()
        self.players_rankings_position(update_places=True) 
        return True

    """ def ranking_add_match(self,match):
        for match_relation in match.players_relations:
            win = 1 if (match.winner == 1 and match_relation.team == 'Home') or  (match.winner == -1 and match_relation.team == 'Away') else 0
            draw = 1 if match.winner == 0 else 0
            player =  match_relation.player
            ranking_points_non_average = (player.ranking_points) * (len(player.divisions_relations) - 1) if (len(player.divisions_relations) - 1) else 0
            ranking_points_non_average += (win * match.division.rating/100 + draw * match.division.rating/250)
            divisions_played = [div for div in player.divisions_relations if div.has_ended]
            n_divisions_played = len(divisions_played) - 1 if divisions_played else 1 
            player.ranking_points = ranking_points_non_average / n_divisions_played
            player.save()
        self.players_rankings_position(update_places=True) 
        return True """