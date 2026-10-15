"""Semantic parity v1 -> v2: the same numbers through both APIs (gate R6).

    python scripts/parity/semantic.py --v1 <v1 capture dir> --code <checkout> --template <db> [--only KEY]

<v1 capture dir> is a capture.py output (golden or candidate). For each v1 page
this script requests the matching /api/v2 resource from <checkout> on a copy of
<template> and compares the fields named in MAP, matching list rows by id.
Rows and fields are compared exactly; v1 values that v1 rounds are compared
with V1_ROUNDING applied to the v2 value (reported as "rounded", not as a match).

Reading rule: docs/v2/qa/gates.md R6. Exit 1 on any mismatch or missing row.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent

WINNER = {1: "home", -1: "away", 0: "draw", None: None}

# ---- mapping -------------------------------------------------------------
# Each page: v1 key pattern -> v2 path, and comparisons. A comparison is
# (label, v1 getter, v2 getter[, kind]); kind "round0"/"round2" means v1 shows the
# value rounded to 0/2 decimals and v2 keeps it unrounded.


def _by_id(rows, key=lambda r: r.get("id")):
    return {key(r): r for r in rows or [] if key(r) is not None}


def _side_ids(match, side):
    return sorted(p["player"]["id"] for p in match.get("participants", [])
                  if p["side"] == side and p.get("player") and p.get("role") == "member")


def group_rows(v1, v2):
    """tournament_<id> (GET /api/v1/tournaments/<id>) vs GET /api/v2/groups/<id>."""
    d = v1["division"]
    yield "group", d["id"], [
        ("name", d.get("name"), v2.get("name")),
        ("rating", d.get("rating"), v2.get("rating")),
        ("hasEnded", d.get("hasEnded"), v2.get("hasEnded")),
        ("members", sorted(p["id"] for p in v1.get("players", []) if p.get("id")),
         sorted(p["id"] for p in v2.get("members", []))),
    ]
    v2s = _by_id(v2.get("standings"), lambda r: r["player"]["id"])
    for r in v1.get("standings", []):
        pid = r["player"]["id"]
        s = v2s.get(pid)
        yield "standing", pid, None if s is None else [
            ("place", r.get("position"), s.get("place")),
            ("points", r.get("points"), s.get("points")),
            ("played", r.get("appearances"), s.get("played")),
            ("wins", r.get("wins"), s.get("wins")),
            ("draws", r.get("draws"), s.get("draws")),
            ("losses", r.get("losts"), s.get("losses")),
            ("gamesWon", r.get("gamesWon"), s.get("gamesWon")),
            ("gamesLost", r.get("gamesLost"), s.get("gamesLost")),
        ]
    v2m = _by_id(v2.get("_matches"))
    for m in v1.get("allMatches", []):
        x = v2m.get(m["id"])
        yield "match", m["id"], None if x is None else [
            ("round", m.get("matchweek"), x.get("round")),
            ("homeGames", m.get("gamesHomeTeam"), x.get("homeScore")),
            ("awayGames", m.get("gamesAwayTeam"), x.get("awayScore")),
            ("winner", WINNER.get(m.get("winner"), m.get("winner")) if m.get("played") else None, x.get("winner")),
            ("played", bool(m.get("played")), x.get("status") in ("played", "walkover")),
            ("court", m.get("field"), x.get("court")),
            ("scheduledAt", (m.get("dateHour") or "")[:16], (x.get("scheduledAt") or "")[:16]),
            ("homePlayers", sorted(p["id"] for p in m.get("homePlayers", []) if p.get("id")), _side_ids(x, "home")),
            ("awayPlayers", sorted(p["id"] for p in m.get("awayPlayers", []) if p.get("id")), _side_ids(x, "away")),
        ]


def player_rows(v1, v2):
    """player_<id> (GET /api/v1/players/<id>) vs GET /api/v2/players/<id>."""
    yield "player", v1["id"], [
        ("name", v1.get("name"), v2.get("name")),
        ("fullName", v1.get("fullName"), v2.get("fullName")),
        ("rankingPosition", v1.get("rankingPosition"), v2.get("rankingPosition")),
        ("rankingPoints", v1.get("rankingPoints"), v2.get("rankingPoints"), "round0"),
        ("height", v1.get("height"), v2.get("height")),
    ]
    v2h = _by_id(v2.get("history"), lambda r: r.get("groupId"))
    for h in v1.get("tournamentHistory", []):
        x = v2h.get(h["divisionId"])
        yield "history", (v1["id"], h["divisionId"]), None if x is None else [
            ("place", h.get("place"), x.get("place")),
            ("played", h.get("played"), x.get("played")),
            ("won", h.get("won"), x.get("wins")),
            ("rankingPoints", h.get("rankingPoints"), x.get("awardPoints"), "round2"),
        ]


def ranking_rows(v1, v2):
    """players_ranking (GET /api/v1/players/ranking) vs GET /api/v2/rankings/current."""
    v2e = _by_id(v2.get("entries"), lambda r: r["player"]["id"])
    for r in v1:
        x = v2e.get(r["id"])
        yield "ranking", r["id"], None if x is None else [
            ("position", r.get("rankingPosition"), x.get("position")),
            ("points", r.get("rankingPoints"), x.get("points"), "round0"),
        ]


def teams_rows(v1, v2):
    """teams_<user> (GET /api/v1/teams/) vs GET /api/v2/competitions/<teams>/teams (same shape)."""
    for k in sorted(set(v1) | set(v2)):
        if k == "miniTournament":  # D8: ids differ
            a = {kk: vv for kk, vv in (v1.get(k) or {}).items() if kk != "id"}
            b = {kk: vv for kk, vv in (v2.get(k) or {}).items() if kk != "id"}
        elif k == "pairs":  # D8: pair ids differ; compare members
            a = sorted(sorted(p.get("playerIds") or [x.get("id") for x in p.get("players", [])]) for p in v1.get(k) or [])
            b = sorted(sorted(p.get("playerIds") or [x.get("id") for x in p.get("players", [])]) for p in v2.get(k) or [])
        else:
            a, b = v1.get(k, "<missing>"), v2.get(k, "<missing>")
        yield "teams", k, [(k, a, b)]


PAGES = [
    # (v1 key regex, v2 path template, row generator, {field: extra v2 path merged into the body})
    (r"tournament_(\d+)$", "/api/v2/groups/{0}", group_rows, {"_matches": "/api/v2/groups/{0}/matches"}),
    (r"player_(\d+)$", "/api/v2/players/{0}", player_rows, {}),
    (r"players_ranking$", "/api/v2/rankings/current", ranking_rows, {}),
    (r"teams_(\d+|anon)$", "/api/v2/competitions/{teams}/teams", teams_rows, {}),
]

# ---- comparison ----------------------------------------------------------


def same(a, b, kind=None):
    num = (int, float)
    if isinstance(a, num) and isinstance(b, num) and not isinstance(a, bool) and abs(a - b) < 1e-9:
        return "equal"
    if kind and isinstance(a, (int, float)) and isinstance(b, (int, float)):
        nd = {"round0": 0, "round2": 2}[kind]
        if a == b:
            return "equal"
        return "rounded" if abs(round(b, nd) - a) <= 10 ** -nd / 2 + 1e-9 else "mismatch"
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return "equal" if abs(a - b) < 1e-9 else "mismatch"
    return "equal" if a == b else "mismatch"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--v1", required=True)
    parser.add_argument("--code", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--run-db", default=None)
    parser.add_argument("--only", default=None)
    parser.add_argument("--show", type=int, default=5)
    args = parser.parse_args()

    run_db = args.run_db or f"{os.environ['TEST_DB_PREFIX']}_semantic_run"
    sys.path.insert(0, str(HERE))
    from capture import FROZEN_NOW, recreate_database

    os.environ.update(FLASK_ENV="development", POSTGRES_HOST="localhost", POSTGRES_USER="postgres",
                      POSTGRES_PW="", POSTGRES_DB=run_db, GCS_UPLOADS_BUCKET="parity-bucket",
                      LLM_API_KEY="", MAIL_PASSWORD="")
    v1dir = Path(args.v1).resolve()
    os.chdir(args.code)
    sys.path.insert(0, str(Path(args.code).resolve()))
    from freezegun import freeze_time

    recreate_database(run_db, args.template)  # v2 GETs never write (D3), so one copy serves all
    import padel_league
    from flask_jwt_extended import create_access_token

    app = padel_league.create_app()
    client = app.test_client()
    urls = {r["key"]: r for r in json.loads((HERE / "urls.json").read_text())}

    def get(path, user_id=None):
        headers = {}
        with freeze_time(FROZEN_NOW):
            if user_id:
                with app.app_context():
                    headers["Authorization"] = "Bearer " + create_access_token(identity=str(user_id))
            r = client.get(path, headers=headers)
        return r.status_code, (r.get_json(silent=True) if r.is_json else None)

    teams_id = None
    st, cur = get("/api/v2/competitions/current?format=teams")
    if st == 200 and isinstance(cur, dict):
        teams_id = cur.get("id")

    counts = defaultdict(Counter)
    problems = defaultdict(list)
    not_impl = Counter()
    for f in sorted(v1dir.glob("*.json")):
        key = f.stem
        if args.only and args.only not in key:
            continue
        for rx, tmpl, gen, extra in PAGES:
            m = re.match(rx, key)
            if not m:
                continue
            page = gen.__name__.replace("_rows", "")
            v1 = json.loads(f.read_text())
            if v1["status"] != 200:
                counts[page]["v1 non-200 (skipped)"] += 1
                break
            path = tmpl.format(*m.groups(), teams=teams_id)
            status, v2 = get(path, (urls.get(key) or {}).get("user_id"))
            if status != 200 or v2 is None:
                not_impl[(page, status)] += 1
                break
            for field, xpath in extra.items():
                xs, xb = get(xpath.format(*m.groups()))
                if xs != 200:
                    not_impl[(page + field, xs)] += 1
                v2[field] = xb if isinstance(xb, list) else (xb or {}).get("matches", xb) if isinstance(xb, dict) else []
            for kind, rid, comps in gen(v1["body"], v2):
                if comps is None:
                    counts[page]["row missing in v2"] += 1
                    problems[page].append(f"{key} {kind} {rid}: no v2 row")
                    continue
                for c in comps:
                    label, a, b = c[:3]
                    verdict = same(a, b, c[3] if len(c) > 3 else None)
                    counts[page][verdict] += 1
                    if verdict != "equal":
                        problems[page].append(f"{key} {kind} {rid} {label}: v1={str(a)[:60]} v2={str(b)[:60]} ({verdict})")
            break

    bad = 0
    for page in sorted(set(counts) | {p for p, _ in not_impl}):
        print(f"== {page}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts[page].items())))
        for (p, st), n in not_impl.items():
            if p == page:
                print(f"   v2 not served ({st}): {n} pages")
        real = [x for x in problems[page] if not x.endswith("(rounded)")]
        rounded = [x for x in problems[page] if x.endswith("(rounded)")]
        bad += len(real)
        for x in real[: args.show]:
            print("   ✗", x)
        for x in rounded[:2]:
            print("   ~", x)
    print(f"\nmismatches + missing rows: {bad}; rounded-only: {sum(c['rounded'] for c in counts.values())}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
