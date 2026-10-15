# S4 — Frontend flows (Wave B)

Worktree `padel_league_frontend-s4`, branch `v2/s4-flows`, Vite port 8082 (Flask 5062 for local API).

## Goal
Everything that writes: result entry, absences with substitute, Teams (pair choice, divisions, set-by-set results, mini-tournament and edition standings), Shuffle admin, competition wizard (Clássica from previous edition, Shuffle, Teams), roster.

## Tasks
1. Result entry: games for Clássica/Shuffle; exactly 3 sets for Teams (win/draw per set, timeout fills draws).
2. Absence: mark absent, pick a substitute player (or unknown); audit visible to admins.
3. Teams: port the master pair page to v2; divisions view; standings per mini-tournament + edition total.
4. Admin: competition wizard (promotion preview from S1), fixtures generation, Shuffle rounds, close group.
5. Optimistic updates with React Query; errors shown inline; phone width first.

## Done when
E2E flows (S6) pass on desktop and phone; no v1 calls left in these features.

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
