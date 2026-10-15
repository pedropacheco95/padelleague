# Production cut-over runbook (v2 database)

Owner of the run: S0 with Pedro. Owner of this doc and the rehearsal: S6.
Reading rules for every check: `docs/v2/qa/gates.md` (R3 verify, R4 rehearsal).
Rehearse with: `TEST_DB_PREFIX=s6 scripts/parity/rehearse_cutover.sh <backup.sql.gz> <label>`.

## Hard ordering rule

**The code production runs today does not work on the migrated database.** Rehearsal
check (15 Oct, `feature/teams-pairs` @ 10ecf65 against a database at `d5a2b8c6e1f4`):
`/api/v1/players/ranking` and `/api/v1/tournaments/77` fail with SQL errors on
`editions`. So the site stays in maintenance from step 3 until the v2 code serves
(step 6). No step may run the old container against the new schema.

The reverse is asserted, not yet tested: v2 code needs the migrated database, so deploy and migrate
together, and roll back both together.

## Steps (production)

Times are from rehearsals on this Mac (r1 on 15 Oct: upgrade 8 s, verify 3 s);
production is an e2-micro, so allow 5–10× that.

| # | Step | Command / action | Check | Rehearsed time |
|---|---|---|---|---|
| 0 | Preconditions | quiet day between jornadas; no result entry in progress; `alembic_version` on prod = `9c2f1a7d4e21` (or `a1d5c0e7b3f2` if the Teams fallback shipped) | value printed | – |
| 1 | Maintenance on | stop the backend container (or switch nginx to the maintenance page) | site shows maintenance | – |
| 2 | Fresh backup | on the box: `scripts/backup.sh` (pg_dump → gzip → GCS); also keep a local copy | file in `gs://portopadelleague-storage/db_backups/`, size close to yesterday's (~147 KB gz) | 1 s |
| 3 | Migrate | from the v2 checkout: `flask db upgrade` against prod (see the prod-env line in `.wolf/cerebrum.md`) | ends at head (`d5a2b8c6e1f4` today) | 8 s |
| 4 | Verify | `scripts/v2/verify_migration.sh padel_league -h <host> -U padel_user` | rule R3: only `matches` 2/2 (D1); `players_in_division` 0/0 or 3/3 (D7) | 3 s |
| 5 | Deploy v2 code | merge/deploy the release commit; container restarts | container up, logs clean | – |
| 6 | Smoke | every URL in `scripts/parity/smoke_urls.txt` answers 200; then the Playwright smoke (`e2e/`) against the live URL | all 200, e2e green | 10 s |
| 7 | Maintenance off | open the site | spot-check home, a tournament, the ranking, Teams | – |

If step 3, 4 or 6 is red: **rollback**.

## Rollback

1. Maintenance stays on (or goes back on).
2. Redeploy the previous container (the commit production ran before step 5).
3. Restore the step-2 backup: drop and recreate `padel_league`, `gunzip -c backup | psql`.
   (The `legacy` schema also holds a copy of every old table, but restore is the plan:
   it is one command and it is what the rehearsal tests.)
4. Check `alembic_version` and the table row counts equal those taken before step 3.
   The rehearsal does this automatically (`pre_*.txt` vs `post_rollback_*.txt`).
5. Maintenance off, smoke the old site.

Rehearsed time for restore + compare: 2 s locally.

## Rehearsal log

| Run | When | Backup | Code | Upgrade+verify | Smoke | Rollback | Verdict |
|---|---|---|---|---|---|---|---|
| r1 | 15 Oct 10:34 | `padel_league_2026-10-15_03-00.sql.gz` | f8b76d8 (= v2/integration 2fc29e2 + S6 files), as superuser | 11 s | 14/14 | identical | GREEN |
| r2 | 15 Oct 10:40 | same | 418da22, restore + upgrade + serve as `padel_user` (db owner, not superuser) | 11 s | 14/14 | identical | GREEN |

Fidelity gaps still open: local server is PostgreSQL 14.13, production 13.23 (dump
header); the rehearsal runs on a Mac, not the e2-micro.

Gate G2 needs two green runs **on the 16 Oct morning backup**; r1 runs on the 15 Oct
backup and counts only as a rehearsal of the procedure.

## Open questions (for S0)

- Step 1: maintenance page or stopped container? Nothing in the repo serves a maintenance
  page today; a stopped container shows nginx 502.
- `CREATE SCHEMA legacy` / `compat` in the migration need CREATE on the database; r2
  passes because `padel_user` owns its database locally. Confirm `padel_user` owns
  `padel_league` in production (`\l padel_league`) before the night.
- Step 3 runs from Pedro's Mac against the public 5432 (cerebrum). Who runs it, and is
  the v2 checkout's `.venv` ready there?
- Today's backup already has division 69 in the computed order, so D7 shows 0/0, not 3/3;
  the comment in `verify_migration.sh` says 3 rows. R3 accepts either.
