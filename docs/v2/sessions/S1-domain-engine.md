# S1 — Domain engine (start now)

Worktree `padelleague-s1`, branch `v2/s1-domain`, `TEST_DB_PREFIX=s1`, no ports.

## Goal
All competition logic as pure, tested functions plus thin services on the v2 models (`models/v2.py`). No HTTP.

## Tasks (in order)
1. `domain/standings.py`: Clássica group standings (points, W/D/L, games, appearances, tie-break by presences then games difference = master c2540a7), live and frozen (`standing_snapshots`).
2. `domain/awards.py`: place points `int(rating·0.75^(pos−1))` + bonus `wins·rating/100 + draws·rating/250`, stored unrounded.
3. Shuffle: place points curve ×0.85 per place 1→8 (2000→641), ×0.90 per place 8→48, `int()`, no bonus. Test the full 48-value table.
4. Teams: mini-tournament standings (set points 3/1/0, presences; ties share the highest place's points), ratings 500/250/125/63/31/16, bonus per set; **reference case** from `docs/v2/teams/reference.md` (P1 534 … P5/P6 100); invariant: every match has exactly 3 set results; walkover 3-0; absent player 0 points.
5. `domain/ranking.py`: rule engine over `awards` — `last_n_completed_plus_current` (2026/27: last 3 completed + current), `per_slot` (2027/28+), no rounding until display; explain per player (which events count).
6. Port `services/promotion.py` and `services/fixtures.py` to v2 entities; Clássica builder (next competition from previous), Shuffle round builder, Teams pairing (mutual, nearest allowed by ranking, never 4th time) and divisions (sum of points, tie: better individual).
7. Close-out service: group complete → snapshot standings → awards → ranking snapshot (fixes B1 order).

## Done when
Unit tests for every rule above pass on Postgres; services covered with factories; no imports from old models or `compat`.

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
