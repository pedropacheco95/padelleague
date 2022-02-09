from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , String , Table, ForeignKey , Boolean, DateTime , Date
from sqlalchemy.orm import relationship

class Division(db.Model ,model.Model , model.Base):
    __tablename__ = 'divisions'
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True)
    name = Column(String(80), unique=True, nullable=False)
    #The first match defines the week day and hour of every other match
    beginning_datetime = Column(DateTime)
    rating = Column(Integer)
    end_date = Column(Date)
    logo_image_path = Column(String(80))
    large_picture_path = Column(String(80))
    has_ended = Column(Boolean)
    edition_id = Column(Integer, ForeignKey('editions.id'))

    edition = relationship('Edition', back_populates="divisions")
    matches = relationship('Match', back_populates="division")
    players_relations = relationship('Association_PlayerDivision', back_populates="division")

    def get_ordered_matches(self):
        self.matches.sort(key=lambda x: x.matchweek)
        return self.matches

    def get_matches_played(self):
        matches_played = [match for match in self.matches if match.played]
        return matches_played

    def get_ordered_matches_played(self):
        matches_played = self.get_matches_played()
        matches_played.sort(key=lambda x: x.matchweek)
        return matches_played

    def tournament_name(self):
        return '{league_name}: {edition_name} {division_name}'.format(league_name=self.edition.league.name, edition_name=self.edition.name,division_name=self.name)

    def players_classification(self,update_places=None):
        return [rel.player for rel in self.players_relations_classification(update_places=None)]

    def players_relations_classification(self,update_places=None):
        sorted_by_points = self.players_relations
        sorted_by_points.sort(key=lambda x: x.points, reverse=True)
        if update_places:
            for index,rel in enumerate(sorted_by_points):
                rel.place = index + 1
                rel.save()
        return sorted_by_points

    def player_position(self,player):
        return self.players_classification().index(player) + 1
    
    def player_in_position(self, position):
        return self.players_classification()[position-1]

    def last_updated_matchweek(self):
        return self.players_relations[0].matchweek

    def update_table(self,force_update=False):
        last_upadted_matchweek = self.last_updated_matchweek()
        matchweek = self.get_ordered_matches_played()[-1].matchweek
        if last_upadted_matchweek != matchweek or force_update:
            for relation in self.players_relations:
                player = relation.player
                wins = len(player.matches_won(self))
                draws = len(player.matches_drawn(self))
                losts = len(player.matches_lost(self))
                games_won = player.games_won(self)
                games_lost = player.games_lost(self)

                points = wins * 3 + draws * 1
                appearances = len(player.matches_played(self))
                percentage_of_appearances = round((appearances / (matchweek+1)*3)*100,2)

                relation.points = points
                relation.appearances = appearances
                relation.percentage_of_appearances = percentage_of_appearances
                relation.wins = wins
                relation.draws = draws
                relation.losts = losts
                relation.games_won = games_won
                relation.games_lost = games_lost
                relation.matchweek = matchweek
                relation.save()
        self.players_classification(update_places=True) 
        return True

    def add_match_to_table(self,match):
        for match_relation in match.players_relations:
            win = 1 if (match.winner == 1 and match_relation.team == 'Home') or  (match.winner == -1 and match_relation.team == 'Away') else 0
            draw = 1 if match.winner == 0 else 0
            lost = 1 if (match.winner == -1 and match_relation.team == 'Home') or  (match.winner == 1 and match_relation.team == 'Away') else 0
            games_won = match.games_home_team
            games_lost = match.games_away_team

            points = win*3 + draw*1

            division_relation = [relation for relation in match_relation.player.divisions_relations if relation.division == self][0]
            division_relation.points += points
            division_relation.appearances += 1
            division_relation.percentage_of_appearances = round((division_relation.appearances / len(self.get_matches_played()))*100,2)
            division_relation.wins += win
            division_relation.draws += draw
            division_relation.losts += lost
            division_relation.games_won += games_won
            division_relation.games_lost += games_lost
            division_relation.matchweek = match.matchweek
            division_relation.save()
        self.players_classification(update_places=True) 
        return True