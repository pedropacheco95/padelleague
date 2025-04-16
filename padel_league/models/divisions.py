from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , String , Table, ForeignKey , Boolean, DateTime , Date
from sqlalchemy.orm import relationship
from padel_league.tools import tools

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
    has_ended = Column(Boolean,default=False)
    open_division = Column(Boolean,default=False)
    edition_id = Column(Integer, ForeignKey('editions.id'))

    edition = relationship('Edition', back_populates="divisions")
    matches = relationship('Match', back_populates="division")
    players_relations = relationship('Association_PlayerDivision', back_populates="division")

    def create(self,vals=None):
        if vals:
            self.name = vals['name']
            self.beginning_datetime = vals['beginning_datetime']
            self.rating = vals['rating']
            self.end_date = vals['end_date']
            self.logo_image_path = vals['logo_image_path']
            self.large_picture_path = vals['large_picture_path']
            self.rating = vals['rating']
            self.edition_id = vals['edition_id']
        super().create()
        return True

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
    
    def get_last_matchweek_and_matches(self):
        matches = self.get_ordered_matches_played()
        matchweek = matches[-1].matchweek
        return matchweek, [match for match in matches if match.matchweek == matchweek]

    def tournament_name(self):
        return '{league_name}: {edition_name} {division_name}'.format(league_name=self.edition.league.name, edition_name=self.edition.name,division_name=self.name)

    def players_classification(self,update_places=None):
        return [rel.player for rel in self.players_relations_classification(update_places)]

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
        matchweek = self.get_ordered_matches_played()[-1].matchweek if self.get_ordered_matches_played() else 0
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
        games_not_played = [match for match in self.matches if not match.played]
        if not games_not_played:
            if not self.has_ended:
                self.edition.league.update_rankings()
                self.has_ended = True
            sorted_matches = sorted(self.matches, key=lambda match: match.date_hour, reverse=True)
            last_played_date = sorted_matches[0].date_hour.date() if sorted_matches else None
            self.end_date = last_played_date
            self.save()
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
            division_relation.percentage_of_appearances = round((division_relation.appearances / len(self.get_matches_played()))*100,2) if len(self.get_matches_played()) else 0
            division_relation.wins += win
            division_relation.draws += draw
            division_relation.losts += lost
            division_relation.games_won += games_won
            division_relation.games_lost += games_lost
            division_relation.matchweek = match.matchweek
            division_relation.save()
        self.players_classification(update_places=True) 
        return True
    
    def last_week_results_string(self):
        matchweek, matches = self.get_last_matchweek_and_matches()

        all_lines = [match.match_dict_line() for match in matches]

        return matchweek, tools.dict_to_table(all_lines)
    
    def get_next_matchweek_games(self,matchweek):
        return tools.dict_to_table([{'Jogo':match.name()} for match in self.matches if match.matchweek == matchweek])
    
    def get_next_matchweek_pairs(self,matchweek):
        games = [match.name() for match in self.matches if match.matchweek == matchweek]
        parelhas = set()
        for game in games:
            parts = game.split(" VS ")
            first_pair = parts[0].strip()
            second_pair = parts[1].strip()
            parelhas.add(first_pair)
            parelhas.add(second_pair)
        
        return list(parelhas)

    
    def get_classications_string(self):

        so = self.players_relations
        player_relations = self.players_relations_classification()

        dict_line = []
        for player_relation in player_relations:
            games = player_relation.wins + player_relation.draws + player_relation.losts
            dict_line.append({
                'Jogador': player_relation.player.name,
                'Lugar': player_relation.place,
                'Pontos': player_relation.points,
                'Pontos por jornada': 3 * (player_relation.points/games) if games else 0,
            })
        return tools.dict_to_table(dict_line)
    
    def get_last_matchweek_points(self):
        matchweek, matches = self.get_last_matchweek_and_matches()
        players = {rel.player.name:0 for rel in self.players_relations}
        for match in matches:
            home_points = 1.5*(match.winner)**2 + 0.5*match.winner + 1
            away_points = 1.5*(match.winner)**2 - 0.5*match.winner + 1
            for player in match.home_players():
                players[player.name] += home_points
            for player in match.away_players():
                players[player.name] += away_points

        return players
    
    def last_played_matches(self, limit=4):
        return sorted(
            [m for m in self.matches if m.played],
            key=lambda m: m.date_hour,
            reverse=True
        )[:limit]