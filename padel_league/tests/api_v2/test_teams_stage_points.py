"""Parelhas per mini-tournament (Pedro, 4 Nov): the points as it started, not the current ones, and
what each player earned once the division closed. Any stage but the acting one is read-only."""

from datetime import datetime, timedelta

from padel_league.models.v2 import Award, AwardEvent, Entry, RankingEntry, RankingSnapshot, Stage
from padel_league.services import ranking, teams_pairing
from padel_league.sql_db import db
from padel_league.tests.api_v2.conftest import bearer, check, persist
from padel_league.tests.api_v2.test_auth_teams import TEAMS, _open_pairing, _roster_players

PATH = "/competitions/{competitionId}/teams"


def _state(client, stage=None, headers=None):
    url = f"/api/v2/competitions/{TEAMS}/teams" + (f"?stage={stage.id}" if stage else "")
    return check(client.get(url, headers=headers or {}), PATH)


def _pair(stage):
    a, b = _roster_players()
    teams_pairing.set_pair(stage, a.id, b.id)
    persist()
    return a, b


def _close_division(stage, gains):
    """An award event for the stage, then the snapshot it produced: everyone's points grow by 1000."""
    start = ranking.current_snapshot()
    event = AwardEvent(competition_id=stage.competition_id, stage_id=stage.id, awarded_at=datetime.utcnow(), source="test")
    db.session.add(event)
    db.session.flush()
    for player, (place_points, bonus_points) in gains.items():
        entry = Entry.query.filter_by(competition_id=stage.competition_id, player_id=player.id).one()
        db.session.add(
            Award(award_event_id=event.id, entry_id=entry.id, player_id=player.id, place=1, rating=500, place_points=place_points, bonus_points=bonus_points, wins=1, draws=0)
        )
    later = RankingSnapshot(league_id=start.league_id, rule_id=start.rule_id, computed_at=datetime.utcnow() + timedelta(seconds=1), is_dry_run=False)
    db.session.add(later)
    db.session.flush()
    for e in RankingEntry.query.filter_by(snapshot_id=start.id):
        db.session.add(RankingEntry(snapshot_id=later.id, player_id=e.player_id, points=float(e.points or 0) + 1000, position=e.position, source=e.source))
    persist()


def test_points_stay_those_at_the_start_and_gains_appear_when_the_division_closes(client):
    stage = _open_pairing()
    a, b = _pair(stage)
    before = _state(client)
    pair = before["pairs"][0]
    assert pair["gains"] is None
    assert not before["miniTournament"]["ended"]

    _close_division(stage, {a: (500, 9.0), b: (375, 4.5)})
    after = _state(client)
    closed = after["pairs"][0]
    assert closed["rankingPoints"] == pair["rankingPoints"]  # not the 2000 points higher of the new snapshot
    assert closed["startPoints"] == pair["startPoints"]
    assert sum(s["points"] for s in closed["startPoints"]) == closed["rankingPoints"]
    assert {s["playerId"] for s in closed["startPoints"]} == {a.id, b.id}
    assert {g["playerId"]: g["points"] for g in closed["gains"]} == {a.id: 509.0, b.id: 379.5}
    assert closed["movement"] is None


def test_a_later_stage_shows_the_current_points(client):
    stage = _open_pairing()
    a, b = _pair(stage)
    start = _state(client)["pairs"][0]["rankingPoints"]
    _close_division(stage, {a: (500, 0.0), b: (375, 0.0)})
    later = Stage.query.filter_by(competition_id=TEAMS, number=2).one()
    body = _state(client, later)
    by_id = {p["id"]: p for p in body["players"]}
    assert by_id[a.id]["rankingPoints"] + by_id[b.id]["rankingPoints"] == start + 2000
    assert body["pairs"] == []


def test_a_stage_other_than_the_acting_one_is_read_only(client, make_user):
    _open_pairing()
    later = Stage.query.filter_by(competition_id=TEAMS, number=2).one()
    admin = make_user(role="admin")
    assert _state(client, headers=bearer(admin))["me"]["isAdmin"]
    body = _state(client, later, headers=bearer(admin))
    assert body["miniTournament"]["id"] == later.id
    assert not body["me"]["isAdmin"] and not body["miniTournament"]["pairingOpen"]


def test_an_unknown_stage_is_a_404(client):
    _open_pairing()
    other = Stage.query.filter(Stage.competition_id != TEAMS).first()
    check(client.get(f"/api/v2/competitions/{TEAMS}/teams?stage={other.id}"), PATH, status=404)
    check(client.get(f"/api/v2/competitions/{TEAMS}/teams?stage=x"), PATH, status=400)
