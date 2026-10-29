"""Conquistas: one test per badge on a hand-built league, plus the registry invariants and
the holder counts of the 50-badge proposal recomputed on the 29 Oct 2026 production snapshot.

The league fixture builds the same League object player_story loads from Postgres, without a
database: competitions, groups, entries and matches are declared by the test, so each badge
is checked at its threshold and one step below it.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from padel_league.services import badges
from padel_league.services.badges import BY_KEY, player_facts
from padel_league.services.player_story import League, Match

ME = 1
SNAPSHOT = Path(__file__).parent / "fixtures" / "badges_prod_2026_10_29.json"


class Fixture:
    """A league declared match by match. Opponent/partner ids above 1000 are other members."""

    def __init__(self):
        self.league = League.__new__(League)
        L = self.league
        L.today = date(2026, 10, 29)
        L.comps, L.matches, L.groups = {}, {}, {}
        L.by_player, L.member_groups, L.entries = defaultdict(list), defaultdict(set), defaultdict(list)
        L.group_rounds = defaultdict(dict)
        L.players, L.refs = {}, {}
        self._mid = self._rid = 0
        self._next_round = defaultdict(int)

    def competition(self, cid, name, fmt="classica", status="ended", starts_on=None):
        self.league.comps[cid] = SimpleNamespace(
            id=cid, name=name, title=None, format=fmt, status=status,
            starts_on=starts_on or date(2022, 1, 1) + timedelta(days=90 * cid), ends_on=None,
        )
        return cid

    def group(self, gid, cid, tier=1, members=(ME,)):
        self.league.groups[gid] = SimpleNamespace(id=gid, stage_id=cid, tier=tier, name=f"{tier}ª Divisão", competition_id=cid, size=8)
        for pid in members:
            self.league.member_groups[pid].add(gid)
        return gid

    def entry(self, pid, cid, place=None, status="active"):
        self.league.entries[pid].append(SimpleNamespace(id=len(self.league.entries[pid]) + 1, player_id=pid, competition_id=cid, status=status, final_place=place))

    def night(self, gid, round_no=None, day=None):
        """The group's next round (or the given one) with, so far, no match of mine; returns the round id."""
        self._rid += 1
        round_no = round_no or self._next_round[gid] + 1
        self._next_round[gid] = max(self._next_round[gid], round_no)
        cid = self.league.groups[gid].competition_id
        day = day or self.league.comps[cid].starts_on + timedelta(days=7 * (round_no - 1))
        self.league.group_rounds[gid][self._rid] = (day, round_no, cid, False)
        return self._rid

    def match(self, gid, rid, home, away, sets, order=0):
        """sets: [(home_games, away_games)]; winner by games (one set) or by sets (three sets)."""
        self._mid += 1
        day, round_no, cid, _ = self.league.group_rounds[gid][rid]
        comp = self.league.comps[cid]
        m = Match(
            id=self._mid, group_id=gid, round_id=rid, round_no=round_no, competition_id=cid, format=comp.format,
            tier=self.league.groups[gid].tier, day=day, estimated=False,
            order=(day, datetime.combine(day, datetime.min.time()) + timedelta(minutes=order), self._mid),
            home=sorted(home), away=sorted(away), sets=list(sets),
        )
        if len(sets) == 1:
            h, a = sets[0]
        else:
            h = sum(1 for x, y in sets if x > y)
            a = sum(1 for x, y in sets if y > x)
        m.winner = "home" if h > a else "away" if a > h else "draw"
        self.league.matches[m.id] = m
        for pid in m.home + m.away:
            self.league.by_player[pid].append(m)
        return m

    def results(self, gid, results, *, partner=None, opponents=None, sets=None, per_night=1):
        """My results in order ("W"/"L"/"D"), one night per `per_night` matches, in the given group."""
        night = None
        for i, r in enumerate(results):
            if i % per_night == 0:
                night = self.night(gid)
            p = partner(i) if callable(partner) else (partner or 1000 + i)
            o = opponents(i) if callable(opponents) else (opponents or (2000 + 2 * i, 2001 + 2 * i))
            s = sets(i, r) if callable(sets) else sets or [{"W": (9, 4), "L": (4, 9), "D": (6, 6)}[r]]
            self.match(gid, night, [ME, p], list(o), s, order=i % per_night)

    def facts(self, pid=ME, teams_titles=None):
        self.league.classic_order = None  # the league keeps growing in a test; drop the memo
        for pid_ in self.league.by_player:
            self.league.by_player[pid_].sort(key=lambda m: m.order)
        return player_facts(self.league, pid, teams_titles or {})


def earned(fx, key, pid=ME):
    b = BY_KEY[key]
    facts = fx.facts(pid)
    value = facts[b.metric]
    assert b.kind != "leader", "leader badges are compared league-wide, not here"
    return badges._earned(b, value, b.target)


@pytest.fixture
def fx():
    f = Fixture()
    f.competition(1, "1ª Edição")
    f.group(10, 1, tier=2)
    return f


# --- volume -------------------------------------------------------------------------------


@pytest.mark.parametrize("key,target", [("clube_100", 100), ("clube_300", 300), ("clube_400", 400)])
def test_clube_counts_matches_played(fx, key, target):
    fx.results(10, "L" * (target - 1))
    assert not earned(fx, key)
    fx.results(10, "L")
    assert earned(fx, key)


def test_mil_games_sums_my_games_over_every_set(fx):
    fx.results(10, "W" * 111, sets=lambda i, r: [(9, 4)])  # 999 games
    assert fx.facts()["games_won"] == 999 and not earned(fx, "mil_games")
    fx.results(10, "L", sets=lambda i, r: [(1, 9)])
    assert earned(fx, "mil_games")


# --- títulos e pódios ---------------------------------------------------------------------


@pytest.mark.parametrize("key,target", [("campeao", 1), ("bicampeao", 2), ("tricampeao", 3)])
def test_titles_count_first_places_in_ended_competitions(fx, key, target):
    for n in range(target - 1):
        fx.entry(ME, fx.competition(20 + n, f"{n + 2}ª Edição"), place=1)
    fx.entry(ME, fx.competition(40, "9ª Edição", status="ongoing"), place=1)  # not ended: no title yet
    assert not earned(fx, key)
    fx.entry(ME, fx.competition(41, "10ª Edição"), place=1)
    assert earned(fx, key)


def test_dinastia_needs_titles_in_consecutive_classica_editions(fx):
    fx.entry(ME, 1, place=1)
    fx.entry(ME, fx.competition(2, "2ª Edição"), place=3)
    fx.entry(ME, fx.competition(3, "3ª Edição"), place=1)
    assert fx.facts()["consecutive_titles"] == 1 and not earned(fx, "dinastia")
    fx.entry(ME, fx.competition(4, "4ª Edição"), place=1)
    assert earned(fx, "dinastia")


def test_habitue_podio_counts_top_three_finishes(fx):
    for n, place in enumerate((1, 2, 3, 3)):
        fx.entry(ME, fx.competition(20 + n, f"{n + 2}ª Edição"), place=place)
    fx.entry(ME, fx.competition(30, "7ª Edição"), place=4)
    assert not earned(fx, "habitue_podio")
    fx.entry(ME, fx.competition(31, "8ª Edição"), place=2)
    assert earned(fx, "habitue_podio")


def test_prata_counts_second_places_only(fx):
    for n, place in enumerate((2, 2, 1, 3)):
        fx.entry(ME, fx.competition(20 + n, f"{n + 2}ª Edição"), place=place)
    assert not earned(fx, "prata")
    fx.entry(ME, fx.competition(30, "7ª Edição"), place=2)
    assert earned(fx, "prata")
