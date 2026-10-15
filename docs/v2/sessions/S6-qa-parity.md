# S6 — QA & parity (start now)

Worktree `padelleague-s6` (+ frontend checkout for e2e), branch `v2/s6-qa`, `TEST_DB_PREFIX=s6`, ports 5064/8084.

## Goal
Make 'done' measurable and the cut-over boring.

## Tasks
1. `scripts/parity/`: per-database prefix (no fixed names); recapture golden after S0's master merge.
2. Semantic parity v1↔v2: for every group, player and the ranking, compare v1 JSON numbers with v2 JSON numbers via an explicit field mapping; report regressions vs listed intended differences.
3. Playwright e2e (`e2e/`): login + token renewal, result entry, absence + substitute, Teams pair choice, ranking page; desktop and 375px.
4. Visual diff old vs new pages (screenshots per route).
5. Cut-over rehearsal script: fresh backup → migrate → verify → smoke → rollback, timed; write the runbook in `docs/v2/qa/cutover.md`.

## Done when
One command reports parity + e2e for the integration branch; two clean rehearsals recorded.

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
