# S5 — Platform & cleanup (start now; cut-over critical path first)

Worktree `padelleague-s5`, branch `v2/s5-platform`, `TEST_DB_PREFIX=s5`, Flask port 5063.

## Goal
Make every remaining write work on v2 (so prod can move to the v2 database), then move the editor, chatbot, skills and tools off the old tables.

## Tasks (in order)
1. **Critical path:** port v1/legacy writes still raising `CompatWriteError`: shuffle admin actions, division create/update, `generate_matches`, `services/editions.py` create-edition CLI, editor `_swap_player_in_division`/readd, editor generic CRUD for competition models, CSV loaders (`uploads.py`, `tools.py`). Each needs a write scenario for S6's parity harness.
2. Editor on v2 models (generic CRUD lists/forms for competitions, stages, groups, rounds, entries, matches, absences, awards).
3. Remove legacy Jinja competition pages once React covers them (keep editor + auth).
4. Chatbot: schema prompt and SQL over v2 tables (read-only connection stays).
5. Skills `create-edition`, `start-next-edition`, `do-linear-ticket`: replace raw SQL on old tables.
6. Substitutes Excel import (`services/imports/substitutes.py`) when Pedro sends the file.

## Done when
No code path writes through `compat`; editor, chatbot and skills only use v2 tables; tests green.

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
