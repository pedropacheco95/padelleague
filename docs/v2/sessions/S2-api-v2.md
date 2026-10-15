# S2 — API v2 (start now; contract draft in plan section 4)

Worktree `padelleague-s2`, branch `v2/s2-api`, `TEST_DB_PREFIX=s2`, Flask port 5061.

## Goal
`/api/v2` blueprints implementing `docs/v2/api/openapi.yaml` on top of S1's services. v1 stays untouched.

## Tasks
1. Package `padel_league/api_v2/`: blueprint per resource (seasons, competitions, groups, matches, rounds, players, rankings, calendar, auth, teams).
2. Serializers from v2 models only; numbers unrounded; camelCase.
3. Roles: `users.role` (player/admin/super_admin) guard decorators; GET never writes.
4. Error format `{error, code}`; 400/401/403/404/409.
5. Contract tests: every endpoint's response validates against the spec (helper from S0).
6. Performance: no N+1 on group and ranking pages (eager loading; one query per list).

## Done when
All spec endpoints implemented, contract tests green, S6 semantic parity green for the corresponding v1 pages.

## Timeline
Everything lands on `v2/integration` **today (15 Oct)**; Teams launches on v2 tomorrow morning. Prioritise what Teams launch and the DB cut-over need, merge small and often, report to S0 every finished task.

## Read first (every session)
- `docs/v2/APP_MIGRATION_PLAN.md` (whole plan, ownership table, conventions), `docs/v2/PLAN.md` (DB migration), `docs/v2/INTENDED_DIFFERENCES.md`.
- `.wolf/cerebrum.md` (rules, Do-Not-Repeat), `.wolf/anatomy.md` before opening files.
- Repos: backend `padelleague/padelleague` (Flask, SQLAlchemy 1.4, venv `.venv`), frontend `padelleague/padel_league_frontend` (Vite + React + TS, pnpm).
- Local Postgres: `postgres@localhost`, no password. Template DBs are listed in `docs/v2/APP_MIGRATION_PLAN.md`.

## Hard rules
- Own worktree + branch from `v2/integration`. Edit only the paths you own; ask S0 (SendMessage) for anything else.
- Databases only under your `TEST_DB_PREFIX`. Never connect to production (35.205.246.86) or call prod endpoints.
- No alembic revisions, no edits to `models/v2.py`, `openapi.yaml`, generated types: request them from S0.
- No push / PR without Pedro's approval; before any gh write `gh auth switch -u pedropacheco95`, then switch back.
- Chain shell steps with `&&`; interactive commands in detached tmux; never ask Pedro for secrets.
- Log to `.wolf/memory.md`, bugs to `.wolf/buglog.json`, learnings to `.wolf/cerebrum.md`.
- When done or blocked: SendMessage to S0 with what changed, tests run, and open questions.
