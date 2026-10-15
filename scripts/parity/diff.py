"""Compare two parity captures and report every difference.

    python scripts/parity/diff.py <golden_dir> <candidate_dir> [--show N]

Normalisation is limited to what the old code itself does not keep stable
between two identical runs (see `normalise`). Differences listed in
INTENDED_DIFFERENCES (keyed by request key prefix + JSON path prefix) are
reported separately as expected.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

D1 = "D1 matches 85/86 attached to division 3"
D1_MATCH_PAGES = {"tournament_3", "calendar_2022-03", "calendar_div_3_2022-03"}

# (request key, json path prefix, reason). Keys match exactly unless they end
# in "*" (prefix); paths match whole segments (".a" does not cover ".ab").
INTENDED_DIFFERENCES = [
    # D1: matches 85 and 86 had no division; they are division 3, jornada 1.
    # On the pages listing matches (D1_MATCH_PAGES) those two matches are
    # dropped from both sides instead, so the rest of the page is still compared.
    # The four players of those matches now have them in their division 3 history.
    ("player_8", ".body.tournamentHistory[7]", D1),
    ("player_12", ".body.tournamentHistory[3]", D1),
    # Indexes from the 2026-10-15 golden (newest edition first, so they move as history grows).
    ("player_13", ".body.tournamentHistory[9]", D1),
    ("player_16", ".body.tournamentHistory[5]", D1),
    ("players_all", ".body[12].tournamentHistory[7]", D1),
    ("players_all", ".body[53].tournamentHistory[9]", D1),
    ("players_all", ".body[72].tournamentHistory[3]", D1),
    ("players_all", ".body[54].tournamentHistory[5]", D1),
    # D8: Teams mini-tournaments are v2 stages, so their (and pairs') ids change.
    ("teams_*", ".body.miniTournament.id", "D8 Teams ids are v2 stage/pair ids"),
    ("teams_*", ".body.pairs", "D8 Teams ids are v2 stage/pair ids"),
    # D2: after an edit, the old schema moved the edited row to the end of the
    # table's physical order. "Last 4 played" breaks date ties by that order,
    # so which tied matches it picks changed after any edit; v2 keeps the
    # original order.
    ("edit_score*", ".body[1].body.division.lastPlayedMatches", "D2 physical row order after an edit"),
]



def _drop_d1_matches(o):
    if isinstance(o, dict):
        return {k: _drop_d1_matches(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_drop_d1_matches(x) for x in o if not (isinstance(x, dict) and x.get("id") in (85, 86))]
    return o


def _sort_players(body):
    if isinstance(body, dict) and isinstance(body.get("players"), list):
        body["players"] = sorted(body["players"], key=lambda p: (p.get("id") is None, p.get("id")))


def normalise(key, body):
    # The old code returns a tournament's player list in arbitrary order.
    if key.startswith("tournament_"):
        _sort_players(body)
    # Write scenarios: a list of step results.
    if isinstance(body, list) and body and isinstance(body[0], dict) and "method" in body[0]:
        for step in body:
            if step["path"].startswith("/api/v1/tournaments/"):
                _sort_players(step["body"])
            # D2: in the old schema an UPDATE moved the edited row to the end
            # of the table's physical order, reordering lists after any edit.
            # v2 keeps the original order, so compare these lists by id.
            sb = step["body"]
            if isinstance(sb, dict):
                for holder in (sb, sb.get("division") if isinstance(sb.get("division"), dict) else {}):
                    for k in ("allMatches", "matches", "events", "lastPlayedMatches"):
                        if isinstance(holder.get(k), list):
                            holder[k] = sorted(holder[k], key=lambda m: str(m.get("id")))
    return body


def walk(a, b, path, out):
    if type(a) is not type(b):
        out.append((path, a, b))
    elif isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            walk(a.get(k, "<missing>"), b.get(k, "<missing>"), f"{path}.{k}", out)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append((path + ".length", len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            walk(x, y, f"{path}[{i}]", out)
    elif a != b:
        out.append((path, a, b))


def _key_matches(kp, key):
    return key.startswith(kp[:-1]) if kp.endswith("*") else key == kp


def _path_matches(pp, path):
    return path == pp or (path.startswith(pp) and path[len(pp)] in ".[") or pp == ""


def intended(key, path):
    for kp, pp, reason in INTENDED_DIFFERENCES:
        if _key_matches(kp, key) and _path_matches(pp, path):
            return reason
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("golden")
    parser.add_argument("candidate")
    parser.add_argument("--show", type=int, default=3, help="differences to print per request")
    args = parser.parse_args()

    golden, cand = Path(args.golden), Path(args.candidate)
    regressions, expected = Counter(), Counter()
    missing = []
    for g in sorted(golden.glob("*.json")):
        key = g.stem
        c = cand / g.name
        if not c.exists():
            missing.append(key)
            continue
        ga, ca = json.loads(g.read_text()), json.loads(c.read_text())
        if key in D1_MATCH_PAGES:
            if ga != ca:
                expected[D1] += 1
            ga["body"], ca["body"] = _drop_d1_matches(ga["body"]), _drop_d1_matches(ca["body"])
        diffs = []
        walk(
            {"status": ga["status"], "body": normalise(key, ga["body"])},
            {"status": ca["status"], "body": normalise(key, ca["body"])},
            "",
            diffs,
        )
        real = [d for d in diffs if not intended(key, d[0])]
        reasons = {intended(key, d[0]) for d in diffs} - {None}
        for reason in reasons:
            expected[reason] += 1
        if real:
            regressions[key] = len(real)
            print(f"✗ {key}  ({len(real)} differences)")
            for path, a, b in real[: args.show]:
                print(f"    {path}: {str(a)[:90]!s}  →  {str(b)[:90]!s}")

    print()
    print(f"requests compared: {len(list(golden.glob('*.json'))) - len(missing)}")
    print(f"regressions: {len(regressions)}")
    for reason, n in expected.items():
        print(f"expected ({reason}): {n} requests")
    if missing:
        print(f"missing in candidate: {len(missing)} e.g. {missing[:5]}")
    return 1 if regressions or missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
