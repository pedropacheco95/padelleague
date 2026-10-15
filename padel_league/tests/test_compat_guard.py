"""Generic editor CRUD / CSV loaders refuse compat models; legacy deletes run on v2."""

import random
from datetime import datetime

from padel_league.models.v2 import Competition, CompetitionGroup, CompetitionMatch
from padel_league.services.fixtures import generate_group_fixtures
from padel_league.sql_db import db
from padel_league.tests import factories as f


def _admin_client(app):
    from flask.sessions import SecureCookieSessionInterface

    app.session_interface = SecureCookieSessionInterface()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True
    return client


def test_generic_writes_refuse_compat_models(pg):
    c = _admin_client(pg)
    for path in ("/api/edit/Division/77", "/api/delete/Match/3189", "/api/modal_create_page/Edition",
                 "/api/upload_csv_to_db/Association_PlayerMatch"):
        r = c.post(path, json={"values": {"name": "x"}})
        assert r.status_code == 409, path
        assert "só de leitura" in r.get_json()["error"]
    r = c.post("/api/remove_relationship", json={"model_name1": "Player", "model_name2": "Division",
                                                 "field_name": "x", "id1": 1, "id2": 77})
    assert r.status_code == 409


def test_editor_create_refuses_compat_models(pg):
    r = _admin_client(pg).post("/editor/create/Division", data={"name": "nope"})
    assert r.status_code == 302
    assert CompetitionGroup.query.filter_by(name="nope").first() is None


def test_generic_writes_still_work_for_public_tables(pg):
    plr = f.player()
    r = _admin_client(pg).post(f"/api/edit/Player/{plr.id}", json={"values": {"name": "Renamed Player"}})
    assert r.status_code == 200 and r.get_json()["success"] is True


def _unplayed_group():
    stage = f.stage(f.competition(name=f"Guard {datetime.utcnow().timestamp()}"))
    grp = f.group(stage, starts_at=datetime(2026, 11, 3, 21, 30))
    for _ in range(8):
        f.member(grp, f.entry(stage.competition, f.player()))
    db.session.expire(grp, ["members"])
    generate_group_fixtures(grp, rng=random.Random(1), commit=False)
    return grp


def test_delete_tournament_deletes_an_unplayed_group(pg):
    grp = _unplayed_group()
    gid, comp_id = grp.id, grp.stage.competition_id
    r = _admin_client(pg).post(f"/api/delete_tournament/{gid}")
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    db.session.expire_all()
    assert db.session.get(CompetitionGroup, gid) is None
    assert CompetitionMatch.query.filter_by(group_id=gid).count() == 0
    assert db.session.get(Competition, comp_id).entries == []


def test_delete_tournament_refuses_a_played_group(pg):
    r = _admin_client(pg).post("/api/delete_tournament/77")
    assert r.status_code == 409
    assert db.session.get(CompetitionGroup, 77) is not None


def test_delete_player_refuses_a_player_with_entries(pg):
    r = _admin_client(pg).post("/api/delete_player/104")
    assert r.status_code == 409


def test_legacy_edition_create_writes_a_competition(pg):
    r = _admin_client(pg).post("/editions/create", data={"name": "Legacy Ed", "league": "1"})
    assert r.status_code == 302
    assert Competition.query.filter_by(name="Legacy Ed", format="classica").count() == 1


def test_csv_bootstrap_loader_is_disabled(pg):
    assert _admin_client(pg).post("/uploads/upload_csv_to_db").status_code == 410
