"""Fixture generation on the v2 model (Postgres, `pg` fixture, no compat writes).

Rows are written as v2 matches/participants; the assertions read them back
both directly and through the compat views the v1 API still serves.
"""

import random
from collections import Counter
from datetime import datetime, timedelta

import pytest

from padel_league.models import Division, Match
from padel_league.models.v2 import CompetitionMatch, MatchParticipant, Round
from padel_league.services.fixtures import (
    FixtureGenerationError,
    fields_for,
    generate_division_fixtures,
    generate_group_fixtures,
)
from padel_league.sql_db import db
from padel_league.tests import factories as f

START = datetime(2026, 9, 15, 21, 30)


def _group(player_count=8, starts_at=START, stage=None, rating=2000, name=None):
    if stage is None:
        stage = f.stage(f.competition(name=f"Fixtures {datetime.utcnow().timestamp()}"))
    grp = f.group(stage, rating=rating, name=name, starts_at=starts_at)
    players = []
    for _ in range(player_count):
        plr = f.player()
        f.member(grp, f.entry(stage.competition, plr))
        players.append(plr.id)
    db.session.expire(grp, ["members"])
    return grp, players


def _matches(grp):
    return CompetitionMatch.query.filter_by(group_id=grp.id).order_by(CompetitionMatch.id).all()


def test_generates_seven_matchweeks_of_six_games(pg):
    grp, _ = _group()
    summary = generate_group_fixtures(grp)

    assert summary["matches_created"] == 42
    matches = _matches(grp)
    assert len(matches) == 42
    assert Counter(m.round.number for m in matches) == {mw: 6 for mw in range(1, 8)}
    assert all(m.status == "scheduled" for m in matches)


def test_rounds_are_shared_by_the_stage(pg):
    grp_a, _ = _group(rating=2000, name="A")
    grp_b, _ = _group(stage=grp_a.stage, rating=1000, name="B")
    generate_group_fixtures(grp_a)
    generate_group_fixtures(grp_b)

    rounds = Round.query.filter_by(stage_id=grp_a.stage_id).order_by(Round.number).all()
    assert [r.number for r in rounds] == list(range(1, 8))
    assert [r.date for r in rounds] == [(START + timedelta(days=7 * i)).date() for i in range(7)]
    assert {m.round_id for m in _matches(grp_a)} == {m.round_id for m in _matches(grp_b)}


def test_every_match_has_two_home_and_two_away_members(pg):
    grp, _ = _group()
    generate_group_fixtures(grp)

    for match in _matches(grp):
        slots = sorted((p.side, p.slot, p.role) for p in match.participants)
        assert slots == [("away", 1, "member"), ("away", 2, "member"), ("home", 1, "member"), ("home", 2, "member")]
        assert all(p.entry_id is not None and p.entry.player_id == p.player_id for p in match.participants)


def test_each_player_partners_every_other_exactly_once(pg):
    grp, player_ids = _group()
    generate_group_fixtures(grp)

    appearances, partnerships = Counter(), Counter()
    for match in _matches(grp):
        for side in ("home", "away"):
            pair = tuple(sorted(p.player_id for p in match.participants if p.side == side))
            partnerships[pair] += 1
            appearances.update(pair)

    assert appearances == {player_id: 21 for player_id in player_ids}
    assert len(partnerships) == 28
    assert set(partnerships.values()) == {3}


def test_dates_are_weekly_and_fields_alternate(pg):
    grp, _ = _group()
    generate_group_fixtures(grp)

    matches = _matches(grp)
    for match in matches:
        assert match.scheduled_at == START + timedelta(days=7 * (match.round.number - 1))
    for matchweek in range(1, 8):
        assert [m.court for m in matches if m.round.number == matchweek] == ["Campo 1", "Campo 2"] * 3


def test_each_group_of_a_stage_gets_its_own_pair_of_courts(pg):
    stage = f.stage(f.competition(name="Courts"))
    groups = [f.group(stage, tier=i + 1, rating=2000 // (2**i), name=f"Masters - {i + 1}a") for i in range(6)]
    db.session.expire(stage, ["groups"])
    assert [fields_for(g) for g in groups] == [
        ("Campo 1", "Campo 2"),
        ("Campo 3", "Campo 4"),
        ("Campo 5", "Campo 6"),
        ("Campo 7", "Campo 8"),
        ("Campo 9", "Campo 10"),
        ("Campo 11", "Campo 12"),
    ]


def test_fields_can_be_overridden_explicitly(pg):
    grp, _ = _group()
    summary = generate_group_fixtures(grp, fields=("Campo 7", "Campo 8"))
    assert summary["fields"] == ["Campo 7", "Campo 8"]
    assert {m.court for m in _matches(grp)} == {"Campo 7", "Campo 8"}


def test_end_date_is_the_last_matchweek_not_a_week_later(pg):
    grp, _ = _group()
    summary = generate_group_fixtures(grp)

    expected = (START + timedelta(days=7 * 6)).date()
    assert summary["end_date"] == expected.isoformat()
    assert grp.end_date.date() == expected


def test_seats_map_every_player_exactly_once(pg):
    grp, player_ids = _group()
    seats = generate_group_fixtures(grp)["seats"]
    assert sorted(seats) == [f"Player {i}" for i in range(1, 9)]
    assert sorted(seats.values()) == sorted(player_ids)


def test_same_rng_seed_gives_the_same_draw(pg):
    grp, _ = _group()
    first = generate_group_fixtures(grp, rng=random.Random(7))["seats"]
    second = generate_group_fixtures(grp, rng=random.Random(7), force=True)["seats"]
    assert first == second


@pytest.mark.parametrize("player_count", [0, 7, 9])
def test_refuses_wrong_player_count(pg, player_count):
    grp, _ = _group(player_count=player_count)
    with pytest.raises(FixtureGenerationError, match="exactly 8"):
        generate_group_fixtures(grp)


def test_refuses_without_beginning_datetime(pg):
    grp, _ = _group(starts_at=None)
    with pytest.raises(FixtureGenerationError, match="beginning_datetime"):
        generate_group_fixtures(grp)


def test_refuses_to_overwrite_existing_matches(pg):
    grp, _ = _group()
    generate_group_fixtures(grp)
    with pytest.raises(FixtureGenerationError, match="already has 42 matches"):
        generate_group_fixtures(grp)


def test_force_regenerates_when_nothing_has_been_played(pg):
    grp, _ = _group()
    generate_group_fixtures(grp)
    assert generate_group_fixtures(grp, force=True)["matches_created"] == 42

    matches = _matches(grp)
    assert len(matches) == 42
    assert MatchParticipant.query.filter(MatchParticipant.match_id.in_([m.id for m in matches])).count() == 42 * 4


def test_force_is_refused_once_a_match_has_been_played(pg):
    grp, _ = _group()
    generate_group_fixtures(grp)
    match = _matches(grp)[0]
    match.set_score(6, 3)
    match.status = "played"
    db.session.flush()

    with pytest.raises(FixtureGenerationError, match="already been played"):
        generate_group_fixtures(grp, force=True)
    assert len(_matches(grp)) == 42


def test_v1_views_show_the_generated_fixtures(pg):
    """What the v1 API reads (compat views) matches what the old code wrote."""
    grp, player_ids = _group()
    summary = generate_division_fixtures(Division.query.get(grp.id))
    assert summary["division_id"] == grp.id

    db.session.expire_all()
    division = Division.query.get(grp.id)
    matches = Match.query.filter_by(division_id=grp.id).all()
    assert len(matches) == 42
    assert Counter(m.matchweek for m in matches) == {mw: 6 for mw in range(1, 8)}
    assert all(m.played is False and m.winner is None for m in matches)
    for match in matches:
        assert Counter(rel.team for rel in match.players_relations) == {"Home": 2, "Away": 2}
    assert division.end_date == datetime(2026, 10, 27)  # midnight, like the migrated groups
    assert sorted(rel.player_id for rel in division.players_relations) == sorted(player_ids)


def _auth_header(user_id=1):
    from flask_jwt_extended import create_access_token

    return {"Authorization": f"Bearer {create_access_token(identity=str(user_id))}"}


def test_endpoint_generates_fixtures_and_names_the_draw(pg):
    grp, player_ids = _group()
    response = pg.test_client().post(f"/api/v1/divisions/{grp.id}/generate_matches", json={}, headers=_auth_header())

    assert response.status_code == 201, response.get_data(as_text=True)
    body = response.get_json()
    assert body["matches_created"] == 42
    assert sorted(seat["id"] for seat in body["seats"].values()) == sorted(player_ids)
    assert all(seat["name"] for seat in body["seats"].values())
    assert len(_matches(grp)) == 42


def test_endpoint_requires_authentication(pg):
    grp, _ = _group()
    response = pg.test_client().post(f"/api/v1/divisions/{grp.id}/generate_matches", json={})
    assert response.status_code == 401
    assert _matches(grp) == []


def test_endpoint_reports_a_conflict_instead_of_crashing(pg):
    grp, _ = _group()
    client, headers = pg.test_client(), _auth_header()
    client.post(f"/api/v1/divisions/{grp.id}/generate_matches", json={}, headers=headers)
    response = client.post(f"/api/v1/divisions/{grp.id}/generate_matches", json={}, headers=headers)
    assert response.status_code == 409
    assert "already has 42 matches" in response.get_json()["message"]
