from padel_league import model
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , String , Text, ForeignKey
from sqlalchemy.orm import relationship

class League(db.Model ,model.Model, model.Base):
    __tablename__ = 'leagues'
    __table_args__ = {'extend_existing': True}
    page_title = 'Ligas'
    model_name = 'League'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(80), unique=True, nullable=False)

    editions = relationship('Edition', back_populates="league")

    def all_players_that_played(self):
        Association = self.editions[0].divisions[0].players_relations[0].__class__
        all_associations = Association.query.all()

        all_editions = sorted(self.editions, key=lambda x: x.id, reverse=True)
        last_four_editions = all_editions[:4]
        last_divisions = []
        for edition in last_four_editions:
            last_divisions += [division for division in edition.divisions if division.has_ended]
        return list(set([assoc.player for assoc in all_associations if assoc.division in last_divisions]))

    def players_rankings_position(self,update_places=False):
        players = list(set(self.all_players_that_played()))
        if any(player.ranking_position == 0 for player in players):
            self.update_rankings()
        players.sort(key=lambda x: (-x.ranking_points, x.ranking_position))
        if update_places:
            for index,player in enumerate(players):
                player.ranking_position = index + 1
                player.save()
        return players

    def update_rankings(self):
        """
        Update the ranking points for all players based on the latest four editions.
        For each player, this function computes ranking points from divisions they played
        in editions that have ended. Points are calculated using the division rating,
        a decay factor based on the player's placement, and additional points for wins and draws.
        """
        # Determine the most recent four editions.
        editions = sorted(self.editions, key=lambda edition: edition.id, reverse=True)
        editions = [edition for edition in editions if (not edition.has_ended()) and (not edition.is_open_division())]
        recent_editions = sorted(self.editions, key=lambda edition: edition.id, reverse=True)[:4]

        # Process each player who has participated.
        for player in self.all_players_that_played():
            total_points = 0
            
            # Filter player's division relations to only those in recent editions with ended divisions.
            recent_division_relations = [
                relation for relation in player.divisions_relations
                if relation.division.edition in recent_editions
            ]
            
            for relation in recent_division_relations:
                total_points += relation.compute_ranking_points()
            
            # Update player's ranking points and set the default ranking position.
            player.ranking_points = total_points
            player.ranking_position = 1
            player.save()
        
        # Update ranking positions based on the new points.
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
            player.ranking_points = ranking_points_non_average / n_divisions_played if n_divisions_played else 0
            player.save()
        self.players_rankings_position(update_places=True)
        return True """