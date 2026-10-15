"""POST /api/v1/editions, POST|PUT /api/v1/divisions write v2 rows (no compat writes)."""

from datetime import datetime

from flask_jwt_extended import create_access_token

from padel_league.models.v2 import AuditEvent, Competition, CompetitionGroup, Entry, GroupMember
from padel_league.sql_db import db
from padel_league.tests import factories as f


def _h():
    return {"Authorization": f"Bearer {create_access_token(identity='1')}"}


def _body(edition_id, players, **kw):
    tag = datetime.utcnow().strftime("%H%M%S%f")
    body = {
        "edition_id": edition_id,
        "name": f"API {tag} - 1ª Divisão",
        "beginning_datetime": "2026-11-03T21:30:00",
        "rating": 2000,
        "end_date": "2026-12-15",
        "has_ended": False,
        "open_division": False,
        "logo_image_id": None,
        "large_picture_id": None,
        "players": [{"player_id": p, "order_index": i} for i, p in enumerate(players, 1)],
    }
    body.update(kw)
    return body


def _edition(client):
    r = client.post("/api/v1/editions", json={"name": f"Ed {datetime.utcnow().timestamp()}"}, headers=_h())
    assert r.status_code == 201, r.get_data(as_text=True)
    return r.get_json()["id"]


def test_post_edition_creates_a_classica_competition_with_a_stage(pg):
    eid = _edition(pg.test_client())
    comp = db.session.get(Competition, eid)
    assert comp.format == "classica" and comp.season.name == "2026/27"
    assert [s.number for s in comp.stages] == [1]


def test_post_division_creates_group_entries_and_members_in_order(pg):
    client = pg.test_client()
    eid = _edition(client)
    players = [f.player().id for _ in range(8)]
    r = client.post("/api/v1/divisions", json=_body(eid, players[::-1]), headers=_h())
    assert r.status_code == 201, r.get_data(as_text=True)
    body = r.get_json()
    assert body["editionId"] == eid and body["standingsUpToDate"] is True

    grp = db.session.get(CompetitionGroup, body["id"])
    assert grp.tier == 1 and grp.stage.competition_id == eid
    assert [m.entry.player_id for m in grp.members] == players[::-1]
    assert [m.seed for m in grp.members] == list(range(1, 9))
    assert AuditEvent.query.filter_by(entity="group", entity_id=grp.id, action="created").count() == 1

    page = client.get(f"/api/v1/tournaments/{grp.id}").get_json()
    assert page is not None


def test_put_division_replaces_members_retiers_and_drops_unused_entries(pg):
    client = pg.test_client()
    eid = _edition(client)
    players = [f.player().id for _ in range(17)]
    a = client.post("/api/v1/divisions", json=_body(eid, players[:8], rating=1000), headers=_h()).get_json()
    b = client.post("/api/v1/divisions", json=_body(eid, players[8:16], rating=500), headers=_h()).get_json()
    assert [db.session.get(CompetitionGroup, x["id"]).tier for x in (a, b)] == [1, 2]

    new_players = [players[16]] + players[9:16]
    r = client.put(f"/api/v1/divisions/{b['id']}", json=_body(eid, new_players, rating=4000, name="Renamed"), headers=_h())
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["name"] == "Renamed"

    db.session.expire_all()
    ga, gb = (db.session.get(CompetitionGroup, x["id"]) for x in (a, b))
    assert (gb.tier, ga.tier) == (1, 2)
    assert [m.entry.player_id for m in gb.members] == new_players
    # player 8 is in no group of this edition any more, and had no matches
    assert Entry.query.filter_by(competition_id=eid, player_id=players[8]).first() is None
    assert GroupMember.query.join(Entry).filter(Entry.competition_id == eid).count() == 16


def test_put_missing_division_is_404(pg):
    eid = _edition(pg.test_client())
    r = pg.test_client().put("/api/v1/divisions/999999", json=_body(eid, []), headers=_h())
    assert r.status_code == 404


def test_post_division_to_unknown_edition_is_400(pg):
    r = pg.test_client().post("/api/v1/divisions", json=_body(999999, []), headers=_h())
    assert r.status_code == 400
    assert "edition_id 999999 was not found" in r.get_json()["message"]


def test_division_writes_require_admin(pg):
    assert pg.test_client().post("/api/v1/divisions", json={}).status_code == 401
    assert pg.test_client().post("/api/v1/editions", json={"name": "x"}).status_code == 401


def test_post_division_without_end_date_answers_instead_of_500(pg):
    """bug-500: the old serializer crashed on a division with no end_date."""
    client = pg.test_client()
    eid = _edition(client)
    players = [f.player().id for _ in range(8)]
    r = client.post("/api/v1/divisions", json=_body(eid, players, end_date=None), headers=_h())
    assert r.status_code == 201, r.get_data(as_text=True)[:300]
    assert r.get_json()["editionShortDateString"] == "Sem data"
