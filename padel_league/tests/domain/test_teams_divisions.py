"""Teams divisions builder: pure seeding + the real 2026/27 roster on Postgres."""

from datetime import datetime

import pytest

from padel_league.domain.errors import Conflict
from padel_league.models.v2 import Competition, CompetitionMatch, GroupMember, Stage
from padel_league.services import closeout, ranking, results, teams_divisions, teams_pairing
from padel_league.services.teams_divisions import seed_pairs, slice_divisions
from padel_league.sql_db import db
from padel_league.tests import factories as f


def test_seed_by_sum_then_best_individual():
    points = {1: 100, 2: 0, 3: 50, 4: 50, 5: 10, 6: 10}
    positions = {1: 1, 2: 9, 3: 2, 4: 3, 5: 4, 6: 5}
    seeded = seed_pairs([(10, (3, 4)), (11, (1, 2)), (12, (5, 6))], points, positions)
    # 100 = 100: pair 11 holds player 1 (position 1) and goes first
    assert [s.pair_id for s in seeded] == [11, 10, 12]


def test_slices_need_multiples_of_four():
    with pytest.raises(Conflict):
        slice_divisions([object()] * 6)
    assert [len(d) for d in slice_divisions(list(range(24)))] == [4] * 6


def _teams_stage1():
    comp = Competition.query.filter_by(format="teams").order_by(Competition.id.desc()).first()
    if comp is None:
        pytest.skip("no Teams competition in template")
    stage = Stage.query.filter_by(competition_id=comp.id, number=1).one()
    stage.pairing_deadline = datetime(2026, 10, 18, 23, 0)
    return comp, stage


def _without_shuffle_awards():
    """Back to the pre-bootstrap state (works on a bootstrapped template too)."""
    from padel_league.models.v2 import AwardEvent, RankingSnapshot

    events = AwardEvent.query.filter_by(competition_id=26).all()
    ids = [e.id for e in events]
    if ids:
        RankingSnapshot.query.filter(RankingSnapshot.after_award_event_id.in_(ids)).delete(synchronize_session=False)
    for event in events:
        db.session.delete(event)
    db.session.flush()


def test_seeding_refuses_while_the_shuffle_has_no_awards(pg):
    comp, stage = _teams_stage1()
    _without_shuffle_awards()
    with pytest.raises(teams_pairing.PairingError) as err:  # v1 endpoints catch PairingError only
        teams_pairing.close(stage)
    assert err.value.__cause__.code == "ranking_missing_awards"


def test_real_roster_pairs_divisions_and_first_group_close(pg):
    comp, stage = _teams_stage1()
    ranking.bootstrap()  # the cut-over step (a no-op once the template is bootstrapped)
    teams_pairing.close(stage)
    assert len(teams_pairing.stage_pairs(stage)) == 24

    built = teams_divisions.build_divisions(stage)
    assert [g.tier for g, _ in built] == [1, 2, 3, 4, 5, 6]
    assert [g.rating for g, _ in built] == [500, 250, 125, 63, 31, 16]
    sums = [sp.points for _, division in built for sp in division]
    assert sums == sorted(sums, reverse=True)
    for group, _ in built:
        assert GroupMember.query.filter_by(group_id=group.id).count() == 8
        matches = CompetitionMatch.query.filter_by(group_id=group.id).all()
        assert len(matches) == 6 and all(len(m.participants) == 4 for m in matches)

    with pytest.raises(Conflict):
        teams_divisions.build_divisions(stage)

    # play and close division 1: every match home 2 sets, 1 time-out draw
    top = built[0][0]
    for m in CompetitionMatch.query.filter_by(group_id=top.id):
        results.record_sets(m.id, [{"home_games": 6, "away_games": 3}] * 2 + [{"outcome": "timeout_draw"}])
    db.session.flush()
    event = closeout.close_group(top.id)
    assert len(event.awards) == 8 and all(a.rating == 500 for a in event.awards)
    assert max(a.place_points for a in event.awards) == 500
    # the closed mini-tournament group now counts in the live ranking (Teams = current)
    assert comp.id in ranking.compute(comp.season.league_id).counted_competition_ids


def test_walkover_on_a_built_match_only_the_absent_player_loses_the_presence(pg):
    comp, stage = _teams_stage1()
    ranking.bootstrap()
    teams_pairing.close(stage)
    group, division = teams_divisions.build_divisions(stage)[5]
    match = CompetitionMatch.query.filter_by(group_id=group.id).order_by(CompetitionMatch.id).first()
    home = [p.entry_id for p in match.participants if p.side == "home"]
    came, absent = [(p.entry_id, p.player_id) for p in match.participants if p.side == "away"]
    results.mark_absent(group.id, match.round.number, absent[1])  # no substitute found
    results.record_sets(match.id, walkover_winner="home")
    db.session.flush()
    db.session.expire_all()
    from padel_league.services.standings import group_standings

    rows = {r.entry_id: r for r in group_standings(group.id).rows}
    assert all((rows[e].points, rows[e].appearances, rows[e].sets_won) == (9, 1, 3) for e in home)
    assert (rows[came[0]].points, rows[came[0]].appearances) == (0, 1)  # turned up: keeps the presence
    assert (rows[absent[0]].points, rows[absent[0]].appearances) == (0, 0)


def test_mirror_keeps_previously_ranked_players_nonzero(pg):
    from padel_league.models import Player

    _without_shuffle_awards()
    before = {p.id for p in Player.query.filter(Player.ranking_position > 0)}
    ranking.bootstrap()
    after = {p.id: p.ranking_position for p in Player.query.all()}
    assert all(after[pid] > 0 for pid in before)
    ranked = sorted(v for v in after.values() if v > 0)
    assert ranked == list(range(1, len(ranked) + 1))


def test_bootstrap_is_idempotent(pg):
    _without_shuffle_awards()
    first = ranking.bootstrap()
    assert first[0] == "awarded shuffle 26" and "written" in first[-1]
    assert ranking.bootstrap() == [f"ranking snapshot {ranking.latest_snapshot(1).id} already current"]


def test_building_the_first_divisions_starts_the_competition(pg):
    """Prod, Oct 2026: Teams 2026/27 stayed 'planned' (card said "upcoming") with 24 matches
    played — nothing flipped it. Building a mini-tournament's divisions starts the Teams."""
    comp, stage = _teams_stage1()
    ranking.bootstrap()
    teams_pairing.close(stage)
    comp.status = "planned"
    teams_divisions.build_divisions(stage)
    assert stage.status == "running" and comp.status == "running"


def test_building_divisions_leaves_a_started_or_ended_competition_alone(pg):
    comp, stage = _teams_stage1()
    ranking.bootstrap()
    teams_pairing.close(stage)
    comp.status = "running"
    teams_divisions.build_divisions(stage)
    assert comp.status == "running"
    # An ended Teams never gets new divisions: the seeding guard refuses it first (no awards
    # for an "ended" competition in the window), and its status is left as it was.
    comp.status = "ended"
    stage2 = Stage.query.filter_by(competition_id=comp.id, number=2).one()
    stage2.pairing_deadline = datetime(2026, 10, 18, 23, 0)
    with pytest.raises(Conflict):
        teams_divisions.build_divisions(stage2)
    assert comp.status == "ended"


# ── artwork carry-over between mini-tournaments ──────────────────────────────


def _image(key):
    from padel_league.model import Image

    image = Image(object_key=key, content_type="image/jpeg", size_bytes=1, is_public=True)
    db.session.add(image)
    db.session.flush()
    return image.id


def test_next_stage_groups_inherit_the_previous_stage_artwork_by_name(pg):
    comp = f.competition(format="teams", name="Teams artwork")
    s1, s2 = f.stage(comp, number=1, status="ended"), f.stage(comp, number=2)
    poster, banner, own_banner = (_image(f"Division/t{i}.png") for i in range(3))
    f.group(s1, tier=1, name="1.ª Divisão", logo_image_id=poster, large_picture_id=banner)
    f.group(s1, tier=2, name="2.ª Divisão", logo_image_id=poster)
    first = f.group(s2, tier=1, name="1.ª Divisão")
    second = f.group(s2, tier=2, name="2.ª Divisão", large_picture_id=own_banner)
    third = f.group(s2, tier=3, name="3.ª Divisão")  # MT2 has one more division: no donor

    touched = teams_divisions.inherit_artwork(s2)

    assert [g.id for g in touched] == [first.id, second.id]
    assert (first.logo_image_id, first.large_picture_id) == (poster, banner)
    assert (second.logo_image_id, second.large_picture_id) == (poster, own_banner)  # its own banner is kept
    assert (third.logo_image_id, third.large_picture_id) == (None, None)


def test_artwork_comes_from_the_newest_previous_stage_that_has_it(pg):
    comp = f.competition(format="teams", name="Teams artwork 3 stages")
    s1, s2, s3, s4 = (f.stage(comp, number=n) for n in (1, 2, 3, 4))
    poster1, poster2, banner1 = (_image(f"Division/n{i}.png") for i in range(3))
    f.group(s1, tier=1, name="1.ª Divisão", logo_image_id=poster1, large_picture_id=banner1)
    f.group(s2, tier=1, name="1.ª Divisão", logo_image_id=poster2)  # replaced the poster, banner never set
    f.group(s3, tier=1, name="1.ª Divisão")  # built before any artwork existed
    fourth = f.group(s4, tier=1, name="1.ª Divisão")
    other = f.group(f.stage(f.competition(format="teams", name="Other Teams"), number=5), tier=1, name="1.ª Divisão")

    teams_divisions.inherit_artwork(s4)

    assert (fourth.logo_image_id, fourth.large_picture_id) == (poster2, banner1)
    assert teams_divisions.inherit_artwork(s4) == []  # idempotent
    assert (other.logo_image_id, other.large_picture_id) == (None, None)  # other competitions are not donors


def test_build_divisions_carries_the_artwork_to_the_next_mini_tournament(pg):
    comp, stage = _teams_stage1()
    ranking.bootstrap()
    teams_pairing.close(stage)
    built = teams_divisions.build_divisions(stage)
    posters = {group.name: _image(f"Division/mt1_{group.tier}.png") for group, _ in built}
    for group, _ in built:
        group.logo_image_id = posters[group.name]
    db.session.flush()

    stage2 = Stage.query.filter_by(competition_id=comp.id, number=2).one()
    stage2.pairing_deadline = datetime(2026, 10, 18, 23, 0)
    teams_pairing.close(stage2)
    built2 = teams_divisions.build_divisions(stage2)

    assert len(built2) == len(built)
    assert all(group.logo_image_id == posters[group.name] for group, _ in built2)
    assert all(group.large_picture_id is None for group, _ in built2)
