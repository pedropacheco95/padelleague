"""GET /players/<id>/story: live blocks with fixed-template sentences (services/player_story)."""

import json
from datetime import date

import pytest

from padel_league.api_v2.players import get_player_page
from padel_league.services import player_story
from padel_league.services.player_story import COPY, story
from padel_league.tests.api_v2.conftest import check

TODAY = date(2026, 10, 18)


def _texts(node, out):
    if isinstance(node, dict):
        if set(node) == {"key", "text"}:
            out.append(node)
            return
        for v in node.values():
            _texts(v, out)
    elif isinstance(node, list):
        for v in node:
            _texts(v, out)
    return out


def test_story_endpoint(client):
    body = check(client.get("/api/v2/players/27/story"), "/players/{playerId}/story")
    assert body["playerId"] == 27
    check(client.get("/api/v2/players/99999999/story"), "/players/{playerId}/story", status=404)


@pytest.mark.parametrize("pid", [27, 28, 3, 40, 105, 96, 1, 19])
def test_every_player_kind_renders(client, pid):
    """Veterans, a rookie (105), Shuffle-only (96), retired (1), no matches (19)."""
    check(client.get(f"/api/v2/players/{pid}/story"), "/players/{playerId}/story")


def test_sentences_come_from_the_catalogue(pg):
    for pid in (27, 28, 3, 105, 96, 1):
        for line in _texts(story(pid, TODAY), []):
            key = line["key"]
            assert key == "hero" or key in COPY or key.startswith("archetype."), key


def test_deterministic(pg):
    a = json.dumps(story(27, TODAY), sort_keys=True)
    player_story._cache.clear()
    b = json.dumps(story(27, TODAY), sort_keys=True)
    assert a == b


def test_headline_numbers_match_the_player_page(pg):
    """Nights = the page's jornadas jogadas/faltadas; matches in rings + excluded = matches played."""
    for pid in (27, 28, 40, 105, 96):
        stats = get_player_page(pid).get_json()["stats"]
        s = story(pid, TODAY)
        assert s["nights"]["played"] == stats["matchweeksPlayed"]
        assert s["nights"]["missed"] == stats["matchweeksMissed"]
        drawn = sum(len(r["matches"]) for r in s["fingerprint"]["rings"]) + s["fingerprint"]["excluded"]
        assert drawn == stats["matchesPlayed"]


def test_rival_matches_compare(client):
    s = story(27, TODAY)
    riv = s["rival"]
    cmp = check(client.get(f"/api/v2/players/compare?a=27&b={riv['player']['id']}"), "/players/compare")
    assert (riv["wins"], riv["draws"], riv["losses"]) == (
        cmp["headToHead"]["aWins"],
        cmp["headToHead"]["draws"],
        cmp["headToHead"]["bWins"],
    )
    assert riv["together"] == {k: cmp["together"][k] for k in ("played", "wins", "draws", "losses")}


def test_malafaya(pg):
    s = story(27, TODAY)
    assert s["hero"]["titles"] == 4 and s["hero"]["editions"] == 18
    assert s["archetype"]["name"] == "Diesel de sangue-frio"
    assert s["people"]["carrasco"]["player"]["name"] == "Fred"
    assert s["nights"]["best"]["net"] == 18
    assert [i["current"] for i in s["streaks"]["items"]] == [5, 3, 0]


def test_minimum_data_rules(pg):
    rookie = story(105, TODAY)
    assert rookie["rival"] is None and rookie["people"] is None
    assert rookie["archetype"]["key"] is None
    assert rookie["mountain"]["title"]["key"] == "mountain.title.rookie"
    shuffle_only = story(96, TODAY)
    assert shuffle_only["mountain"] is None and shuffle_only["fingerprint"]["rings"][0]["format"] == "shuffle"
    retired = story(1, TODAY)
    assert retired["streaks"]["title"]["key"] == "streaks.title.paused"
    assert not any(i["alive"] for i in retired["streaks"]["items"])


def test_substitute_only_player(client):
    """Only substitute seats (external subs; the template may have none): hero line only."""
    from sqlalchemy import text

    from padel_league.sql_db import db

    pid = db.session.execute(
        text(
            "select player_id from match_participants group by player_id "
            "having bool_and(role = 'substitute') order by player_id limit 1"
        )
    ).scalar()
    if pid is None:
        pytest.skip("no substitute-only player in this template")
    body = check(client.get(f"/api/v2/players/{pid}/story"), "/players/{playerId}/story")
    assert all(body[k] is None for k in ("fingerprint", "mountain", "people", "constellation", "rival", "nights", "streaks"))
    assert body["hero"]["line"]["text"].endswith("como substituto")
