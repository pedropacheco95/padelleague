"""Live division standings as the v1 API serves them (compat views over v2 rows).

The old tests drove Division.update_table on SQLite; on v2 the standings are
computed by `compat.players_in_division`, so these build v2 rows and read the
division through the same path the API uses.
"""

from datetime import datetime

from padel_league.models import Division
from padel_league.modules.frontend_api.v1.serializers import serialize_standings_row
from padel_league.sql_db import db
from padel_league.tests import factories as f


class _Division:
    def __init__(self, name):
        self.stage = f.stage(f.competition(name=f"Standings {datetime.utcnow().timestamp()}"))
        self.group = f.group(self.stage, name=name)
        self.rounds = {}
        self.entries = {}

    def add(self, name):
        plr = f.player(name=f"{name} {datetime.utcnow().timestamp()}")
        ent = f.entry(self.stage.competition, plr)
        f.member(self.group, ent)
        self.entries[name] = ent
        return ent

    def entry(self, name):
        # Players outside the division (substitutes) still need an entry to play.
        if name not in self.entries:
            plr = f.player(name=f"{name} {datetime.utcnow().timestamp()}")
            self.entries[name] = f.entry(self.stage.competition, plr)
        return self.entries[name]

    def match(self, matchweek, played, home_games=None, away_games=None, home=(), away=()):
        if matchweek not in self.rounds:
            self.rounds[matchweek] = f.round_(self.stage, number=matchweek)
        sets = [(home_games, away_games)] if home_games is not None else []
        f.match(
            self.group,
            self.rounds[matchweek],
            home=[self.entry(n) for n in home],
            away=[self.entry(n) for n in away],
            sets=sets,
            status="played" if played else "scheduled",
        )

    def standings(self):
        db.session.expire_all()
        division = Division.query.get(self.group.id)
        ordered = division.players_relations_classification()
        names = {e.player_id: n for n, e in self.entries.items()}
        rows = [serialize_standings_row(rel, pos) for pos, rel in enumerate(ordered, start=1)]
        return ordered, {names[rel.player_id]: row for rel, row in zip(ordered, rows)}, names


def test_standings_include_appearances_wins_draws_losses_and_games(pg):
    d = _Division("Division 1")
    for name in ("P1", "P2", "P3", "P4", "P5"):  # P5 never plays
        d.add(name)
    d.match(1, True, 6, 3, home=("P1", "P2"), away=("P3", "P4"))
    d.match(1, True, 4, 4, home=("P1", "P2"), away=("P3", "P4"))
    d.match(1, True, 2, 6, home=("P1", "P2"), away=("P3", "P4"))
    d.match(2, False, home=("P1", "P2"), away=("P3", "P4"))

    _, standings, _ = d.standings()
    for name, won, lost in (("P1", 12, 13), ("P2", 12, 13), ("P3", 13, 12), ("P4", 13, 12)):
        row = standings[name]
        assert row["appearances"] == 1  # 3 raw match rows == 1 matchweek
        assert (row["wins"], row["draws"], row["losts"]) == (1, 1, 1)
        assert (row["gamesWon"], row["gamesLost"]) == (won, lost)
        assert row["points"] == 4

    row = standings["P5"]
    assert (row["appearances"], row["wins"], row["draws"], row["losts"]) == (0, 0, 0, 0)
    assert (row["gamesWon"], row["gamesLost"], row["points"]) == (0, 0, 0)


def test_standings_preserve_existing_points_based_ordering(pg):
    d = _Division("Division 2")
    d.add("Winner")
    d.add("Loser")
    d.match(1, True, 6, 0, home=("Winner",), away=("Loser",))
    d.match(2, False, home=("Winner",), away=("Loser",))

    ordered, standings, names = d.standings()
    assert [names[rel.player_id] for rel in ordered] == ["Winner", "Loser"]
    assert standings["Winner"]["points"] > standings["Loser"]["points"]


def test_standings_break_points_ties_by_appearances_then_games_difference(pg):
    d = _Division("Division 3")
    # Added in the "wrong" order so the tie-break has to do the work.
    for name in ("Rare", "Regular", "BigMargin", "SmallMargin"):
        d.add(name)
    d.match(1, True, 6, 5, home=("Rare",), away=("SmallMargin",))
    d.match(1, True, 6, 5, home=("Regular",), away=("BigMargin",))
    d.match(2, True, 6, 0, home=("BigMargin",), away=("Regular",))
    d.match(2, True, 6, 5, home=("SmallMargin",), away=("Substitute",))
    d.match(3, False, home=("Rare",), away=("Regular",))

    ordered, _, names = d.standings()
    assert [names[rel.player_id] for rel in ordered] == [
        "BigMargin",  # 3 pts, 2 presenças, +5
        "SmallMargin",  # 3 pts, 2 presenças, 0
        "Regular",  # 3 pts, 2 presenças, -5
        "Rare",  # 3 pts, 1 presença, +1 — presenças outrank difference
    ]
    assert [rel.place for rel in ordered] == [1, 2, 3, 4]
