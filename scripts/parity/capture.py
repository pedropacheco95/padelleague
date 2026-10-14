"""Replay the parity requests against one version of the backend.

Before every request the run database is recreated from a pristine template,
because several GET endpoints write (standings, rankings, shuffle stats) and
would otherwise change what the next request sees.

    python scripts/parity/capture.py --code <checkout> --template padel_league_baseline --out <dir>

Runs fully offline: no mail password, no LLM key, a fake GCS bucket name, and
the clock frozen at FROZEN_NOW.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg2

FROZEN_NOW = "2026-10-14 12:00:00"
HERE = Path(__file__).parent


def recreate_database(run_db, template):
    conn = psycopg2.connect("dbname=postgres host=localhost user=postgres")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        "select pg_terminate_backend(pid) from pg_stat_activity "
        "where datname in (%s, %s) and pid <> pg_backend_pid()",
        (run_db, template),
    )
    cur.execute(f'drop database if exists "{run_db}"')
    cur.execute(f'create database "{run_db}" template "{template}"')
    conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", required=True, help="checkout whose padel_league package to run")
    parser.add_argument("--template", required=True, help="pristine database to copy before each request")
    parser.add_argument("--out", required=True)
    parser.add_argument("--run-db", default=None)
    parser.add_argument("--only", default=None, help="substring filter on request keys")
    parser.add_argument("--scenarios", action="store_true", help="replay scenarios.json (writes) instead of urls.json")
    args = parser.parse_args()

    run_db = args.run_db or f"{args.template}_run"
    os.environ.update(
        FLASK_ENV="development",
        POSTGRES_HOST="localhost",
        POSTGRES_USER="postgres",
        POSTGRES_PW="",
        POSTGRES_DB=run_db,
        GCS_UPLOADS_BUCKET="parity-bucket",
        LLM_API_KEY="",
        MAIL_PASSWORD="",
    )
    os.chdir(args.code)
    sys.path.insert(0, str(Path(args.code).resolve()))

    from freezegun import freeze_time

    recreate_database(run_db, args.template)
    import padel_league
    from flask_jwt_extended import create_access_token
    from padel_league.sql_db import db

    app = padel_league.create_app()
    client = app.test_client()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.scenarios:
        scenarios = json.loads((HERE / "scenarios.json").read_text())
    else:
        scenarios = [{"key": r["key"], "steps": [r]} for r in json.loads((HERE / "urls.json").read_text())]
    if args.only:
        scenarios = [r for r in scenarios if args.only in r["key"]]

    for scenario in scenarios:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        recreate_database(run_db, args.template)
        results = []
        for step in scenario["steps"]:
            headers = {}
            with freeze_time(FROZEN_NOW):
                if step.get("user_id"):
                    with app.app_context():
                        headers["Authorization"] = "Bearer " + create_access_token(identity=str(step["user_id"]))
                resp = client.open(step["path"], method=step.get("method", "GET"), headers=headers, json=step.get("json"))
            try:
                body = resp.get_json()
            except Exception:  # noqa: BLE001
                body = None
            if body is None:
                body = resp.get_data(as_text=True)[:2000]
            results.append({"path": step["path"], "method": step.get("method", "GET"), "status": resp.status_code, "body": body})
            with app.app_context():
                db.session.remove()
        record = results[0] if len(results) == 1 else {"path": scenario["key"], "status": results[0]["status"], "body": results}
        (out / f"{scenario['key']}.json").write_text(
            json.dumps(record, indent=1, ensure_ascii=False, sort_keys=True)
        )
        print(" ".join(str(r["status"]) for r in results), scenario["key"], flush=True)


if __name__ == "__main__":
    main()
