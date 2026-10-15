"""v1 Shuffle admin endpoints on services.shuffle (Postgres clone, rolled back)."""

from flask_jwt_extended import create_access_token

from padel_league.models import Player, User
from padel_league.sql_db import db

BASE = "/api/v1/shuffle_tournament"


def _admin():
    user = User.query.filter_by(super_admin=True).first()
    return {"Authorization": f"Bearer {create_access_token(identity=str(user.id))}"}


def _create(client, n=16):
    ids = [p.id for p in Player.query.order_by(Player.id).limit(n)]
    body = {
        "title": "Shuffle teste", "max_players": 48, "number_of_divisions": 2, "has_ended": False,
        "division_multipliers": {"1": 10, "2": 8},
        "players": [{"player_id": pid, "order_index": i + 1} for i, pid in enumerate(ids)],
    }  # fmt: skip
    resp = client.post(f"{BASE}/create", json=body, headers=_admin())
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json(), ids


def test_create_generate_calculate_undo_delete(pg):
    client = pg.test_client()
    created, ids = _create(client)
    tid = int(created["id"])
    # membership by order_index; within a division v1 re-sorts by its live order (here ranking points)
    assert [set(d["playerIds"]) for d in created["divisions"]] == [{str(p) for p in ids[:8]}, {str(p) for p in ids[8:]}]

    gen = client.post(f"{BASE}/generate_matchweek", json={"tournamentId": tid}, headers=_admin())
    assert gen.status_code == 200, gen.get_json()
    again = client.post(f"{BASE}/generate_matchweek", json={"tournamentId": tid}, headers=_admin())
    assert again.status_code == 400
    assert again.get_json()["error"] == "Cannot generate a new matchweek while there are unfinished matches."

    removed = client.post(
        f"{BASE}/remove_player_from_matchweek",
        json={"tournamentId": tid, "playerId": ids[0], "matchweek": 1}, headers=_admin(),
    )  # fmt: skip
    assert removed.status_code == 200 and removed.get_json() == {"removedAssociations": 3}

    calc = client.post(f"{BASE}/calculate_divisions", json={"tournamentId": tid}, headers=_admin())
    assert calc.status_code == 200
    assert sorted(len(d["playerIds"]) for d in calc.get_json()["divisions"]) == [8, 8]
    undo = client.post(f"{BASE}/undo_calculate_divisions", json={"tournamentId": tid}, headers=_admin())
    assert undo.status_code == 200

    deleted = client.post(f"{BASE}/delete_last_matchweek", json={"tournamentId": tid}, headers=_admin())
    assert deleted.status_code == 200, deleted.get_json()
    assert (deleted.get_json()["deletedMatches"], deleted.get_json()["deletedMatchweek"]) == (12, 1)
    empty = client.post(f"{BASE}/delete_last_matchweek", json={"tournamentId": tid}, headers=_admin())
    assert empty.status_code == 400 and empty.get_json()["error"] == "No matchweeks found"


def test_ended_shuffle_refuses_a_new_matchweek(pg):
    resp = pg.test_client().post(f"{BASE}/generate_matchweek", json={"tournamentId": 1}, headers=_admin())
    assert resp.status_code == 400 and resp.get_json()["error"] == "This shuffle tournament has ended."
