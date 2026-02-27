import json
import hashlib

from sqlalchemy import Boolean, Column, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from padel_league import model
from padel_league.sql_db import db


class ShuffleTournament(db.Model, model.Model):
    __tablename__ = "shuffle_tournaments"
    __table_args__ = {"extend_existing": True}
    page_title = "Shuffle Tournaments"
    model_name = "ShuffleTournament"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(120), nullable=False, default="Padel Shuffle")
    current_matchweek = Column(Integer, nullable=False, default=1)
    max_players = Column(Integer, nullable=False, default=48)
    number_of_divisions = Column(Integer, nullable=False, default=6)
    has_ended = Column(Boolean, default=False)
    division_multipliers_raw = Column(
        Text,
        nullable=False,
        default='{"1": 10, "2": 8, "3": 6, "4": 5, "5": 4, "6": 3}',
    )

    matches = relationship("ShuffleMatch", back_populates="shuffle_tournament")
    players_relations = relationship(
        "Association_PlayerShuffleTournament", back_populates="shuffle_tournament"
    )

    @hybrid_property
    def name(self):
        return f"{self.title}"

    @property
    def division_multipliers(self):
        try:
            raw = json.loads(self.division_multipliers_raw or "{}")
            return {int(k): int(v) for k, v in raw.items()}
        except (TypeError, ValueError):
            return {}

    @division_multipliers.setter
    def division_multipliers(self, value):
        parsed = {str(int(k)): int(v) for k, v in (value or {}).items()}
        self.division_multipliers_raw = json.dumps(parsed)

    def relation_for_player(self, player_id):
        for rel in self.players_relations:
            if rel.player_id == player_id:
                return rel
        return None

    def _draw_order_for_player(self, player_id):
        """
        Stable draw order (sorteio) per tournament/player to break complete ties.
        """
        digest = hashlib.sha256(f"{self.id}:{player_id}".encode("utf-8")).hexdigest()
        return int(digest[:12], 16)

    def reset_player_stats(self):
        for rel in self.players_relations:
            rel.points = 0
            rel.wins = 0
            rel.draws = 0
            rel.losses = 0
            rel.games_played = 0
            rel.games_won = 0
            rel.games_lost = 0

    def recalculate_player_stats(self):
        self.reset_player_stats()

        for match in self.matches:
            if not match.played:
                continue
            if match.score1 is None or match.score2 is None:
                continue

            multiplier = self.division_multipliers.get(match.division, 1)
            team1_won = match.score1 > match.score2
            is_draw = match.score1 == match.score2

            for rel in match.players_relations:
                t_rel = self.relation_for_player(rel.player_id)
                if not t_rel:
                    continue

                is_home = rel.team == "Home"
                team_score = match.score1 if is_home else match.score2
                opp_score = match.score2 if is_home else match.score1

                t_rel.games_played += 1
                t_rel.games_won += team_score
                t_rel.games_lost += opp_score

                won = (is_home and team1_won) or (
                    (not is_home) and (not team1_won) and (not is_draw)
                )
                if won:
                    t_rel.wins += 1
                    t_rel.points += 3 * multiplier
                elif is_draw:
                    t_rel.draws += 1
                    t_rel.points += 1 * multiplier
                else:
                    t_rel.losses += 1

        ordered = sorted(
            self.players_relations,
            key=lambda rel: (
                -(rel.points or 0),  # 1) Pontos
                -(rel.games_played or 0),  # 2) Presenças na liga atual
                -((rel.games_won or 0) - (rel.games_lost or 0)),  # 3) Diferença jogos
                (
                    rel.player.ranking_position
                    if rel.player and rel.player.ranking_position
                    else 9999
                ),  # 4) Ranking geral
                self._draw_order_for_player(rel.player_id),  # 5) Sorteio
            ),
        )
        for idx, rel in enumerate(ordered, start=1):
            rel.position = idx

        self.save()
        return True
