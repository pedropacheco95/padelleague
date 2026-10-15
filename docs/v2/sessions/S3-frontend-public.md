# S3 — Frontend public pages (Wave A with mocks, then real API)

Worktree `padel_league_frontend-s3`, branch `v2/s3-public`, Vite port 8081.

## Goal
Public pages on the v2 API: competitions list, competition, group page (standings + matches with sets), calendar, players, player page + comparison, ranking with per-event breakdown, home.

## Tasks
1. Use generated types `src/api/v2/schema.d.ts` (from S0) and React Query hooks per feature under `src/features/<area>/`.
2. Until S2 lands, mock with fixtures that validate against the spec (MSW).
3. Shared components in `src/components/v2/`: StandingsTable, MatchCard (games or sets), RoundSelector, PlayerAvatar, PointsValue (rounds only here).
4. Routes `/competitions/:id`, `/groups/:id`, `/players/:id`, `/ranking`, `/calendar`; redirects from `/tournaments/:id` → `/groups/:id` (send route changes to S0, who owns App.tsx).
5. Phone width first; root font-size is 10px — use px Tailwind values.

## Done when
Each page matches the old page's content (S6 visual + semantic checks), works at 375px, no v1 calls left in these features.

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
