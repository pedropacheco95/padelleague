from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from padel_league import model
from padel_league.sql_db import db
from padel_league.tools.input_tools import Block, Field, Form


class Match(db.Model, model.Model):
    __tablename__ = "matches"
    __table_args__ = {"extend_existing": True}
    page_title = "Jogos"
    model_name = "Match"

    id = Column(Integer, primary_key=True, autoincrement=True)
    games_home_team = Column(Integer)
    games_away_team = Column(Integer)
    date_hour = Column(DateTime)
    # This variable should be calculated (maybe specify __init__ fucntion)
    winner = Column(Integer)
    matchweek = Column(Integer, nullable=False)
    field = Column(Text)
    played = Column(Boolean, nullable=False)
    division_id = Column(Integer, ForeignKey("divisions.id"))

    division = relationship("Division", back_populates="matches")
    players_relations = relationship("Association_PlayerMatch", back_populates="match")

    @hybrid_property
    def name(self):
        return f"Match {self.id} from {self.division}"

    def home_players(self):
        return [rel.player for rel in self.players_relations if rel.team == "Home"]

    def away_players(self):
        return [rel.player for rel in self.players_relations if rel.team == "Away"]

    def clean_name(self):
        home_players = self.home_players()
        away_players = self.away_players()
        home0 = home_players[0].name if home_players else "Substituto"
        home1 = home_players[1].name if len(home_players) == 2 else "Substituto"
        away0 = away_players[0].name if away_players else "Substituto"
        away1 = away_players[1].name if len(away_players) == 2 else "Substituto"
        return "{player1} ; {player2} VS {player3} ; {player4}".format(
            player1=home0, player2=home1, player3=away0, player4=away1
        )

    def next_match_to_edit(self):
        matches = self.division.get_ordered_matches()
        matches_not_played = [match for match in matches if not match.played]
        for match in matches_not_played:
            return match
        return None

    def next_match(self):
        match = Match.query.filter_by(id=self.id + 1).first()
        return match if match else None

    def previous_match(self):
        match = Match.query.filter_by(id=self.id - 1).first()
        return match if match else None

    def match_dict_line(self):
        name = self.clean_name()
        teams = name.split(" VS ")
        home_players = teams[0]
        away_players = teams[1]

        winner = (
            home_players
            if self.winner == 1
            else away_players if self.winner == -1 else None
        )
        loser = (
            home_players
            if self.winner == -1
            else away_players if self.winner == 1 else None
        )

        winner_games = (
            self.games_home_team
            if self.games_home_team >= self.games_away_team
            else self.games_away_team
        )
        loser_games = (
            self.games_home_team
            if self.games_home_team <= self.games_away_team
            else self.games_away_team
        )

        score = f"{winner_games} - {loser_games}"

        dict_line = {
            "Players": self.name(),
            "Result": (
                f"{winner} won {score} against {loser}"
                if winner
                else f"{home_players} e {away_players} empataram {score}"
            ),
        }
        return dict_line

    def players_formatted(self):
        home_players = self.home_players()
        away_players = self.away_players()
        home0 = home_players[0].name if home_players else "Substituto"
        home1 = home_players[1].name if len(home_players) == 2 else "Substituto"
        away0 = away_players[0].name if away_players else "Substituto"
        away1 = away_players[1].name if len(away_players) == 2 else "Substituto"

        players = {
            "home": {
                "player1": home0,
                "player2": home1,
                "result": self.games_home_team,
            },
            "away": {
                "player1": away0,
                "player2": away1,
                "result": self.games_away_team,
            },
        }
        return players

    def display_all_info(self):
        searchable_column = {"field": "date_hour", "label": "Data e Hora"}
        table_columns = [
            searchable_column,
            {"field": "division", "label": "Divisão"},
            {"field": "games_home_team", "label": "Jogos Equipa Casa"},
            {"field": "games_away_team", "label": "Jogos Equipa Fora"},
            {"field": "winner", "label": "Vencedor"},
            {"field": "matchweek", "label": "Jornada"},
            {"field": "field", "label": "Campo"},
            {"field": "played", "label": "Jogado?"},
        ]
        return searchable_column, table_columns

    def get_create_form(self):
        def get_field(name, label, type, required=False, related_model=None):
            return Field(
                instance_id=self.id,
                model=self.model_name,
                name=name,
                label=label,
                type=type,
                required=required,
                related_model=related_model,
            )

        form = Form()

        fields = [
            get_field(
                name="date_hour", label="Data e Hora", type="DateTime", required=True
            ),
            get_field(
                name="division",
                label="Divisão",
                type="ManyToOne",
                required=True,
                related_model="Division",
            ),
            get_field(
                name="games_home_team", label="Jogos Equipa Casa", type="Integer"
            ),
            get_field(
                name="games_away_team", label="Jogos Equipa Fora", type="Integer"
            ),
            get_field(name="winner", label="Vencedor", type="Integer"),
            get_field(name="matchweek", label="Jornada", type="Integer", required=True),
            get_field(name="field", label="Campo", type="Text"),
            get_field(name="played", label="Jogado?", type="Boolean", required=True),
        ]
        info_block = Block("info_block", fields)
        form.add_block(info_block)

        return form
