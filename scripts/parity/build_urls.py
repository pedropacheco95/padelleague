"""Build the list of read requests the parity harness replays.

Ids come from the baseline database so the list covers every division,
player and month that exists. Writes the list to urls.json next to this file.

    python scripts/parity/build_urls.py --db padel_league_baseline
"""

import argparse
import json
from pathlib import Path

import psycopg2

HERE = Path(__file__).parent


def months_between(first, last):
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m == 13:
            y, m = y + 1, 1


def build(dsn):
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()

    def rows(sql):
        cur.execute(sql)
        return cur.fetchall()

    urls = []

    def add(key, path, user_id=None):
        urls.append({"key": key, "method": "GET", "path": path, "user_id": user_id})

    add("main_index", "/api/v1/main/index")
    add("tournaments_list", "/api/v1/tournaments/")
    add("editions_list", "/api/v1/editions")
    add("players_ranking", "/api/v1/players/ranking")
    add("players_short_all", "/api/v1/players/short/all")
    add("players_all", "/api/v1/players/all")
    add("shuffle", "/api/v1/shuffle_tournament")
    add("matches_for_edit", "/api/v1/matches/for_edit")
    add("teams_anon", "/api/v1/teams/")

    for (division_id,) in rows("select id from divisions order by id"):
        add(f"tournament_{division_id}", f"/api/v1/tournaments/{division_id}")
        add(f"for_edit_div_{division_id}", f"/api/v1/matches/for_edit?division_id={division_id}")

    for (player_id,) in rows("select id from players order by id"):
        add(f"player_{player_id}", f"/api/v1/players/{player_id}")

    first, last = rows("select min(date_hour), max(date_hour) from matches")[0]
    for month in months_between(first, last):
        add(f"calendar_{month}", f"/api/v1/calendar?month={month}")
    add("calendar_bad_month", "/api/v1/calendar?month=bad")

    # Per-division calendar for each month the division played in.
    for division_id, month in rows(
        "select distinct division_id, to_char(date_hour, 'YYYY-MM') from matches "
        "where division_id is not null order by 1, 2"
    ):
        add(f"calendar_div_{division_id}_{month}", f"/api/v1/calendar/{division_id}?month={month}")

    for (edition_id,) in rows("select id from editions order by id"):
        add(f"last_played_players_{edition_id}", f"/api/v1/divisions/last_played_players?edition_id={edition_id}")

    # Head-to-head: pairs from the latest division and from the shuffle.
    latest = rows("select id from divisions order by id desc limit 1")[0][0]
    members = [r[0] for r in rows(f"select player_id from players_in_division where division_id={latest} order by player_id")]
    for a, b in zip(members, members[1:]):
        add(f"comparison_{latest}_{a}_{b}", f"/api/v1/tournaments/{latest}/player_comparison?player1Id={a}&player2Id={b}")
    shuffle_players = [r[0] for r in rows("select player_id from players_in_shuffle_tournament order by player_id limit 8")]
    for a, b in zip(shuffle_players, shuffle_players[1:]):
        add(f"shuffle_comparison_{a}_{b}", f"/api/v1/shuffle_tournament/player_comparison?tournamentId=1&player1Id={a}&player2Id={b}")

    for user_id, in rows("select id from users order by id limit 3"):
        add(f"auth_me_{user_id}", "/api/v1/auth/me", user_id=user_id)
        add(f"teams_{user_id}", "/api/v1/teams/", user_id=user_id)

    conn.close()
    return urls


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="padel_league_baseline")
    args = parser.parse_args()
    urls = build(f"dbname={args.db} host=localhost user=postgres")
    (HERE / "urls.json").write_text(json.dumps(urls, indent=1))
    print(f"{len(urls)} requests written to {HERE / 'urls.json'}")
