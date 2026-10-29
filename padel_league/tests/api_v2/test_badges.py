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


# --- sequências e presenças ---------------------------------------------------------------


@pytest.mark.parametrize("key,target", [("sete_seguidas", 7), ("dez_seguidas", 10), ("quinze_seguidas", 15)])
def test_win_streaks_break_on_a_draw(fx, key, target):
    fx.results(10, "W" * (target - 1) + "D" + "W" * (target - 1))
    assert not earned(fx, key)
    fx.results(10, "W")
    assert earned(fx, key)


def test_ferro_50_counts_consecutive_nights_present(fx):
    fx.results(10, "L" * 49)
    fx.night(10)  # a night I missed
    fx.results(10, "L" * 30)
    assert fx.facts()["best_attendance"] == 49 and not earned(fx, "ferro_50")
    fx.results(10, "L" * 20)
    assert earned(fx, "ferro_50")


def test_assiduo_counts_ended_editions_without_an_absence(fx):
    for n in range(5):
        cid = fx.competition(20 + n, f"{n + 2}ª Edição")
        gid = fx.group(100 + n, cid, tier=3)
        fx.results(gid, "LLLLLLL")
        if n == 4:
            fx.night(gid)  # one absence in the fifth edition
    assert fx.facts()["full_attendance_editions"] == 4 and not earned(fx, "assiduo")
    gid = fx.group(200, fx.competition(60, "8ª Edição"), tier=3)
    fx.results(gid, "LLLLL")
    assert earned(fx, "assiduo")


@pytest.mark.parametrize("key,target", [("veterano", 10), ("vinte_edicoes", 20)])
def test_editions_count_entries_in_unplanned_competitions(fx, key, target):
    for n in range(target - 1):
        fx.entry(ME, fx.competition(20 + n, f"{n + 2}ª Edição"))
    fx.entry(ME, fx.competition(90, "50ª Edição", status="planned"))
    assert not earned(fx, key)
    fx.entry(ME, fx.competition(91, "51ª Edição", status="ongoing"))
    assert earned(fx, key)


# --- resultados e noites ------------------------------------------------------------------


def test_rolo_compressor_counts_wins_by_five_or_more_games(fx):
    fx.results(10, "W" * 24, sets=lambda i, r: [(9, 4)])
    fx.results(10, "W" * 5, sets=lambda i, r: [(9, 5)])
    assert fx.facts()["big_wins"] == 24 and not earned(fx, "rolo_compressor")
    fx.results(10, "W", sets=lambda i, r: [(5, 0)])
    assert earned(fx, "rolo_compressor")


def test_rei_tiebreak_counts_sets_won_seven_six(fx):
    fx.results(10, "W" * 19, sets=lambda i, r: [(7, 6)])
    fx.results(10, "L" * 5, sets=lambda i, r: [(6, 7)])
    assert fx.facts()["tiebreak_set_wins"] == 19 and not earned(fx, "rei_tiebreak")
    fx.results(10, "W", sets=lambda i, r: [(7, 6)])
    assert earned(fx, "rei_tiebreak")


def test_salomao_counts_draws(fx):
    fx.results(10, "D" * 19 + "WL")
    assert not earned(fx, "salomao")
    fx.results(10, "D")
    assert earned(fx, "salomao")


def test_noite_perfeita_needs_all_three_wins_of_a_night(fx):
    fx.results(10, "WWL", per_night=3)
    assert not earned(fx, "noite_perfeita")
    fx.results(10, "WWW", per_night=3)
    assert earned(fx, "noite_perfeita")


def test_dono_da_noite_counts_perfect_nights(fx):
    fx.results(10, "WWW" * 14 + "WWD", per_night=3)
    assert fx.facts()["perfect_nights"] == 14 and not earned(fx, "dono_da_noite")
    fx.results(10, "WWW", per_night=3)
    assert earned(fx, "dono_da_noite")


def test_ressuscitador_counts_lose_then_win_twice_nights(fx):
    fx.results(10, "LWW" * 7 + "WLW" + "LWL", per_night=3)
    assert fx.facts()["comebacks"] == 7 and not earned(fx, "ressuscitador")
    fx.results(10, "LWW", per_night=3)
    assert earned(fx, "ressuscitador")


# --- parceiros e rivais -------------------------------------------------------------------


def test_sociavel_counts_distinct_partners(fx):
    fx.results(10, "L" * 29, partner=lambda i: 1000 + i)
    fx.results(10, "L" * 5, partner=1000)  # the same partner again
    assert fx.facts()["distinct_partners"] == 29 and not earned(fx, "sociavel")
    fx.results(10, "L", partner=1999)
    assert earned(fx, "sociavel")


def test_quimica_counts_wins_with_one_partner(fx):
    fx.results(10, "W" * 14 + "L" * 3, partner=1000)
    fx.results(10, "W" * 5, partner=1001)
    assert fx.facts()["max_wins_with_partner"] == 14 and not earned(fx, "quimica")
    fx.results(10, "W", partner=1000)
    assert earned(fx, "quimica")


def test_conhece_toda_a_gente_counts_distinct_opponents(fx):
    fx.results(10, "L" * 22, opponents=lambda i: (2000 + 2 * i, 2001 + 2 * i))  # 44 opponents
    assert fx.facts()["distinct_opponents"] == 44 and not earned(fx, "conhece_toda_a_gente")
    fx.results(10, "L", opponents=(2000, 2999))
    assert earned(fx, "conhece_toda_a_gente")


def test_carrasco_counts_wins_against_one_opponent(fx):
    fx.results(10, "W" * 19 + "L" * 4, opponents=(2000, 2001))
    fx.results(10, "W" * 3, opponents=(2002, 2003))
    assert fx.facts()["max_wins_vs_opponent"] == 19 and not earned(fx, "carrasco")
    fx.results(10, "W", opponents=(2000, 2500))
    assert earned(fx, "carrasco")


# --- lealdade e divisões ------------------------------------------------------------------


def test_da_primeira_hora_means_a_match_in_the_play_off_or_first_edition():
    f = Fixture()
    f.group(10, f.competition(1, "Play Off", starts_on=date(2022, 1, 12)))
    f.group(20, f.competition(2, "1ª Edição", starts_on=date(2022, 3, 9)))
    f.group(30, f.competition(3, "2ª Edição", starts_on=date(2022, 10, 12)))
    f.results(30, "WW")
    assert not earned(f, "da_primeira_hora")
    f.results(20, "L")
    assert earned(f, "da_primeira_hora")
    g = Fixture()
    g.group(10, g.competition(1, "Play Off", starts_on=date(2022, 1, 12)))
    g.results(10, "L")
    assert earned(g, "da_primeira_hora")


def test_regresso_means_a_missed_ended_classica_edition_between_two_played(fx):
    fx.results(10, "L")
    fx.competition(2, "2ª Edição")  # ended without me
    assert not earned(fx, "regresso")
    fx.results(fx.group(30, fx.competition(3, "3ª Edição")), "L")
    assert earned(fx, "regresso")
    # Consecutive editions are not a return.
    g = Fixture()
    g.results(g.group(10, g.competition(1, "1ª Edição")), "L")
    g.results(g.group(20, g.competition(2, "2ª Edição")), "L")
    assert not earned(g, "regresso")


def _tiers(f, tiers):
    for n, tier in enumerate(tiers):
        f.group(100 + n, f.competition(20 + n, f"{n + 2}ª Edição"), tier=tier)


def test_elevador_foguetao_and_fenix_read_the_tier_sequence():
    f = Fixture()
    _tiers(f, (4, 3, 3))
    assert earned(f, "elevador") and not earned(f, "foguetao") and not earned(f, "fenix")
    f = Fixture()
    _tiers(f, (4, 3, 2))
    assert earned(f, "foguetao") and not earned(f, "fenix")
    f = Fixture()
    _tiers(f, (2, 3, 2))
    assert earned(f, "fenix") and not earned(f, "foguetao")
    f = Fixture()
    _tiers(f, (2, 3, 3, 2))  # relegated, stayed, then rose: not straight back
    assert not earned(f, "fenix")


def test_elite_counts_classica_editions_in_the_first_division():
    f = Fixture()
    _tiers(f, (1, 1, 1, 1, 2))
    assert f.facts()["first_division_editions"] == 4 and not earned(f, "elite")
    f.group(200, f.competition(60, "9ª Edição"), tier=1)
    assert earned(f, "elite")


# --- shuffle ------------------------------------------------------------------------------


def test_baralhado_means_a_shuffle_match(fx):
    fx.results(10, "W")
    assert not earned(fx, "baralhado")
    fx.results(fx.group(50, fx.competition(5, "20ª Edição", fmt="shuffle")), "L")
    assert earned(fx, "baralhado")


def test_top10_shuffle_reads_the_best_ended_shuffle_place(fx):
    assert fx.facts()["shuffle_best_place"] is None and not earned(fx, "top10_shuffle")
    fx.entry(ME, fx.competition(5, "20ª Edição", fmt="shuffle"), place=11)
    fx.entry(ME, fx.competition(6, "25ª Edição", fmt="shuffle", status="ongoing"), place=1)
    assert fx.facts()["shuffle_best_place"] == 11 and not earned(fx, "top10_shuffle")
    fx.entry(ME, fx.competition(7, "30ª Edição", fmt="shuffle"), place=10)
    assert earned(fx, "top10_shuffle")
