"""create-edition on the v2 model (Postgres, `pg` fixture, no compat writes)."""

import random
from datetime import datetime

import pytest

from padel_league.models import Division, Edition, Match
from padel_league.models.v2 import (
    Competition,
    CompetitionGroup,
    CompetitionMatch,
    Entry,
    GroupMember,
    Round,
    Season,
    Stage,
)
from padel_league.services.editions import (
    EditionPlanError,
    create_edition_from_plan,
    validate_plan,
)
from padel_league.sql_db import db
from padel_league.tests import factories as f

START = "2026-11-03T21:30:00"


def _players(count=16):
    return [f.player().id for _ in range(count)]


def _plan(player_ids, divisions=2, **overrides):
    tag = datetime.utcnow().strftime("%H%M%S%f")
    plan = {
        "edition_name": f"99ª Edição {tag}",
        "league_id": 1,
        "beginning_datetime": START,
        "divisions": [
            {
                "name": f"Teste {tag} - {i + 1}ª Divisão",
                "rating": 2000 // (2**i),
                "players": player_ids[i * 8 : (i + 1) * 8],
            }
            for i in range(divisions)
        ],
    }
    plan.update(overrides)
    return plan


def test_creates_competition_stage_groups_entries_and_fixtures(pg):
    player_ids = _players()
    result = create_edition_from_plan(_plan(player_ids), rng=random.Random(1))

    assert len(result["divisions"]) == 2
    assert all(d["matches_created"] == 42 for d in result["divisions"])

    comp = db.session.get(Competition, result["edition_id"])
    assert (comp.format, comp.status, comp.season.name) == ("classica", "planned", "2026/27")
    assert comp.event_slot_id is None
    assert [s.number for s in comp.stages] == [1]
    stage = comp.stages[0]
    assert (stage.seeding_method, stage.emits_award) == ("promotion", True)
    assert [r.number for r in Round.query.filter_by(stage_id=stage.id).order_by(Round.number)] == list(range(1, 8))
    assert sorted(e.player_id for e in Entry.query.filter_by(competition_id=comp.id)) == sorted(player_ids)
    for grp in stage.groups:
        assert [m.seed for m in grp.members] == list(range(1, 9))
        assert CompetitionMatch.query.filter_by(group_id=grp.id).count() == 42


def test_v1_views_show_the_new_edition_like_the_old_code_wrote_it(pg):
    player_ids = _players()
    plan = _plan(player_ids)
    result = create_edition_from_plan(plan)
    db.session.expire_all()

    edition = Edition.query.get(result["edition_id"])
    assert edition.name == plan["edition_name"]
    assert [d.name for d in edition.divisions] == [d["name"] for d in plan["divisions"]]
    for division, spec in zip(edition.divisions, plan["divisions"]):
        assert division.rating == spec["rating"]
        assert division.beginning_datetime.isoformat() == START
        assert division.has_ended is False
        rels = sorted(division.players_relations, key=lambda r: r.place)
        # place before any result = the plan's seeding order, as the old code stored it
        assert [r.player_id for r in rels] == spec["players"]
        assert Match.query.filter_by(division_id=division.id).count() == 42


def test_tiers_follow_rating_and_courts_follow_the_ladder(pg):
    player_ids = _players(24)
    plan = _plan(player_ids, divisions=3)
    plan["divisions"] = [plan["divisions"][2], plan["divisions"][0], plan["divisions"][1]]
    result = create_edition_from_plan(plan)

    groups = {g.name: g for g in CompetitionGroup.query.filter(CompetitionGroup.id.in_([d["division_id"] for d in result["divisions"]]))}
    by_rating = sorted(groups.values(), key=lambda g: -g.rating)
    assert [g.tier for g in by_rating] == [1, 2, 3]
    fields = {d["division_name"]: d["fields"] for d in result["divisions"]}
    assert [fields[g.name] for g in by_rating] == [["Campo 1", "Campo 2"], ["Campo 3", "Campo 4"], ["Campo 5", "Campo 6"]]


def test_ratings_and_dates_come_from_the_plan(pg):
    result = create_edition_from_plan(_plan(_players()))
    comp = db.session.get(Competition, result["edition_id"])
    assert (comp.starts_on.isoformat(), comp.ends_on.isoformat()) == ("2026-11-03", "2026-12-15")
    groups = sorted(comp.stages[0].groups, key=lambda g: -g.rating)
    assert [g.rating for g in groups] == [2000, 1000]
    for grp in groups:
        assert grp.starts_at.isoformat() == START
        assert grp.end_date.date().isoformat() == "2026-12-15"
        assert grp.has_ended is False


def test_season_and_event_slot_can_be_named(pg):
    result = create_edition_from_plan(_plan(_players(), season="2026/27", event_slot="classica-2"))
    comp = db.session.get(Competition, result["edition_id"])
    assert comp.event_slot.key == "classica-2"


def test_rejects_non_classica_event_slot(pg):
    with pytest.raises(EditionPlanError, match="not a classica slot"):
        validate_plan(_plan(_players(), event_slot="teams"))


def test_rejects_date_outside_every_season(pg):
    with pytest.raises(EditionPlanError, match="no season contains"):
        validate_plan(_plan(_players(), beginning_datetime="2031-01-01T21:30:00"))


def test_rejects_division_with_wrong_player_count(pg):
    player_ids = _players()
    plan = _plan(player_ids)
    plan["divisions"][1]["players"] = player_ids[8:15]
    with pytest.raises(EditionPlanError, match="expected 8 players, got 7"):
        create_edition_from_plan(plan)


def test_rejects_player_in_two_divisions(pg):
    player_ids = _players()
    plan = _plan(player_ids)
    plan["divisions"][1]["players"][0] = player_ids[0]
    with pytest.raises(EditionPlanError, match="is in both"):
        create_edition_from_plan(plan)


def test_rejects_unknown_player(pg):
    plan = _plan(_players())
    plan["divisions"][0]["players"][0] = 999999
    with pytest.raises(EditionPlanError, match="player\\(s\\) not found"):
        create_edition_from_plan(plan)


def test_rejects_duplicate_edition_name(pg):
    with pytest.raises(EditionPlanError, match="already exists"):
        validate_plan(_plan(_players(), edition_name="22ª Edição Masters de Outono"))
    # names are unique across formats, not only among Clássicas
    with pytest.raises(EditionPlanError, match="already exists"):
        validate_plan(_plan(_players(), edition_name="23ª Edição Teams 2026/27"))


def test_next_edition_number_runs_across_every_format(pg):
    from padel_league.services.editions import edition_number, next_edition_number

    assert edition_number("20ª Edição Shuffle Edition") == 20
    assert edition_number("Play Off") is None
    assert next_edition_number() == 24  # 23ª is Teams 2026/27, not a Clássica
    f.competition(name="30ª Edição Shuffle", format="shuffle")
    assert next_edition_number() == 31


def test_edition_name_defaults_to_the_next_number(pg):
    from padel_league.services.editions import preview_plan

    plan = _plan(_players())
    del plan["edition_name"]
    assert preview_plan(plan)["edition_name"] == "24ª Edição"
    result = create_edition_from_plan(plan, rng=random.Random(1))
    assert db.session.get(Competition, result["edition_id"]).name == "24ª Edição"
    assert validate_plan(_plan(_players(), edition_name=""))["edition_name"] == "25ª Edição"


def test_rejects_division_name_already_used(pg):
    plan = _plan(_players(), divisions=1)
    plan["divisions"][0]["name"] = "Masters de Outono - 1ª Divisão"
    with pytest.raises(EditionPlanError, match="division names are unique"):
        validate_plan(plan)


def _counts():
    return tuple(m.query.count() for m in (Competition, Stage, CompetitionGroup, Entry, GroupMember, CompetitionMatch))


def test_nothing_is_written_when_a_later_division_is_invalid(pg):
    player_ids = _players()
    before = _counts()
    plan = _plan(player_ids)
    plan["divisions"][1]["players"] = player_ids[8:15]
    with pytest.raises(EditionPlanError):
        create_edition_from_plan(plan)
    assert _counts() == before


def test_a_failure_while_writing_rolls_the_whole_edition_back(pg, monkeypatch):
    from padel_league.services import editions

    before = _counts()
    calls = []

    def boom(group, **kw):
        calls.append(group.id)
        if len(calls) == 2:
            raise RuntimeError("fixtures failed")
        return {"division_id": group.id}

    monkeypatch.setattr(editions, "generate_group_fixtures", boom)
    with pytest.raises(RuntimeError):
        create_edition_from_plan(_plan(_players()))
    assert _counts() == before


def test_validate_plan_writes_nothing(pg):
    player_ids = _players()
    before = _counts()
    validated = validate_plan(_plan(player_ids))
    assert len(validated["divisions"]) == 2
    assert validated["season_id"] == Season.query.filter_by(name="2026/27").one().id
    assert _counts() == before
    assert Division.query.filter(Division.name.like("Teste %")).count() == 0


def test_preview_plan_shows_the_groups_and_writes_nothing(pg):
    from padel_league.services.editions import preview_plan

    player_ids = _players()
    before = _counts()
    plan = _plan(player_ids)
    plan["divisions"].reverse()
    preview = preview_plan(plan)
    assert _counts() == before
    assert [(d["name"], d["tier"], d["rating"]) for d in preview["divisions"]] == [
        (plan["divisions"][0]["name"], 2, 1000),
        (plan["divisions"][1]["name"], 1, 2000),
    ]
    assert preview["divisions"][0]["players"] == player_ids[8:16]
    with pytest.raises(EditionPlanError):
        preview_plan(_plan(player_ids, edition_name="22ª Edição Masters de Outono"))
