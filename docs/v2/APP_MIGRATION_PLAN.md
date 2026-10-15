# Whole-app migration to the v2 data model

Status: **approved 2026-10-15. Target: everything done today; Teams launches on v2 tomorrow morning (16 Oct)**.

**Go/no-go 16 Oct 08:00 (S0 with Pedro):** go only if gate G2 holds (parity green, two clean rehearsals on that morning's backup, rollback tested). If not: ship the ready fallback `feature/teams-pairs` (Teams pair choice on the old system) so picks still close Sunday, and cut over at the next quiet evening. Owner: coordinator session (S0).
Canonical copy for all sessions. Companion docs: `PLAN.md` (DB migration), `INTENDED_DIFFERENCES.md`, `sessions/*.md` (one brief per session).

## 0. Where we are (2026-10-15)

| Layer | Today on `feature/v2-data-model` | End state |
|---|---|---|
| Database | v2 tables + `legacy` archive + `compat` views (local only; prod untouched) | v2 tables only; `compat` and `legacy` dropped |
| Backend reads | old models (`models/*.py`) over `compat` views | domain services + new models (`models/v2.py`) |
| Backend writes | result, absence, close-out on v2; the rest blocked (`CompatWriteError`) | all on v2 |
| JSON API | `/api/v1` (old shapes) | `/api/v2` designed around the new model; v1 deleted |
| Frontend | unchanged, calls v1 | calls v2, new types generated from the API spec |
| Admin editor (Flask/Jinja) | old models | v2 models (stays in Flask) |
| Chatbot | read-only over `compat` | read-only over v2 tables, new schema prompt |
| Tests | SQLite, 38 erroring | Postgres templates, per-session databases, contract + parity + e2e |

Production runs `master` (old schema). The Teams pair-choice release (`feature/teams-pairs`) adds `teams_*` tables, `users.code_attempts` and cuts `is_admin` to the super admins.

## 1. Decisions needed

| # | Decision | Recommendation |
|---|---|---|
| D1 | Teams on v2 from launch (16 Oct morning) | **Yes**; `feature/teams-pairs` is the fallback if the go/no-go fails |
| D2 | Teams mini-tournament 1 | Runs entirely on v2 (only needed if the fallback ships: thin `teams_*` tables, folded in at cut-over) |
| D3 | Strategy | **Database + Teams first (16 Oct), then remaining page switches**: move prod to the v2 database with the compat layer (old API keeps working), then ship v2 API + frontend in code-only releases, then delete the compat layer |
| D4 | URLs | New routes (`/competitions/:id`, `/groups/:id`), old ones redirect (ids are preserved: division id = group id) |
| D5 | Sessions | Coordinator + 6 workers, all at once |
| D6 | Admin editor | Stays in Flask, rebuilt on v2 models |

## 2. Phases and gates

### Phase 0: foundations (S0 only) — first hours of 15 Oct
1. Merge `master` into the v2 branch (standings tie-break c2540a7, lockdown, Teams release). Re-point `b7d2e4c1a9f0.down_revision` to the Teams revision `a1d5c0e7b3f2`. Recapture the golden parity set (it predates c2540a7) and re-run parity.
2. Migration vs Teams tables: the archive step copies every public table into `legacy` and keeps it in `public`, so `teams_*` and `users.code_attempts` survive. Add a step folding `teams_*` into `competitions/entries/pairs/partner_requests` (new competition "Teams 2026/27"). Add preconditions for the new state.
3. Integration branch `v2/integration`; every session branches from it into its own worktree.
4. Test infrastructure on Postgres:
   - template DB built from the prod backup + migration (`make template`),
   - `TEST_DB_PREFIX` env var: every fixture/script names databases `<prefix>_...`, so sessions never drop each other's databases (fix `test_teams_pairing.py`, `scripts/parity/capture.py`),
   - transactional fixture (each test rolls back) + factories for v2 objects,
   - move the 38 erroring tests.
5. API contract v0: `docs/v2/api/openapi.yaml` for reads and the core writes; TS types generated with `openapi-typescript` into `src/api/v2/schema.d.ts`; contract-test helper that validates any response against the spec.
6. Conventions doc (section 6) and session briefs.

**Gate G0:** integration branch green on Postgres, parity green after the master merge, spec v0 merged, briefs published.

### Phase 1: parallel build — 15 Oct, all sessions at once
Workstreams in section 3. Backend v2 API is added **beside** v1; nothing is removed.

### Phase 2: production database cut-over
Critical path: every v1 write path ported (shuffle admin, division create/update, fixture generation, create-edition CLI, editor swap/readd + generic CRUD, CSV loaders), because after the cut-over v1 still serves the live site.

**Gate G2:**
- parity: 526/526 reads + all write scenarios, only listed differences,
- two full rehearsals on fresh backups (migration, verify script, smoke, rollback),
- runbook signed off,
- a quiet day between jornadas.

Runbook: fresh backup → maintenance banner → `flask db upgrade` → `verify_migration.sh` → smoke (Playwright) → open. Rollback: restore the backup (the `legacy` schema is a second copy).

### Phase 3: switch the app to v2 (code-only releases)
Page by page, the frontend moves to `/api/v2` (feature flag per route while both exist). Each switch needs semantic parity for that page (S6) and an e2e pass. Teams runs on v2 from here.

### Phase 4: delete the old system
Checklist (all must hold):
- no `/api/v1` or legacy Jinja competition requests in nginx logs for 7 days,
- remove `/api/v1`, old models, `compat` views, `CompatWriteError` guard, legacy Jinja competition routes/templates,
- chatbot, skills, scripts reference only v2 tables,
- `legacy` schema dumped to GCS, dropped after 30 days,
- `PLAN.md`, anatomy, cerebrum updated.

## 3. Workstreams and file ownership

Only the owner edits a path. Shared files go through S0 (ask via SendMessage; S0 merges).

| Session | Scope | Owns | Wave |
|---|---|---|---|
| **S0 Coordinator** | Phase 0, API spec, migrations, merges, cut-over, deletion | `models/v2.py`, `migrations/**`, `docs/v2/**`, `openapi.yaml`, `src/api/v2/schema.d.ts`, `App.tsx` routes, `tests/conftest.py` | – |
| **S1 Domain engine** | Pure calculation + services on v2 models: standings (Clássica, Shuffle, Teams), close-out → awards, ranking engine (rules, Shuffle curve, last 3 + current, no rounding), promotion/fixtures port, competition builders (Clássica from previous, Shuffle rounds, Teams pairs/divisions), Teams reference case | `padel_league/domain/**`, `padel_league/services/**`, `tests/domain/**` | A |
| **S2 API v2** | `/api/v2` blueprints, serializers, roles (`users.role`), errors, contract tests | `padel_league/api_v2/**`, `tests/api_v2/**` | B |
| **S3 Frontend: public** | Competitions, group page (standings, matches with sets), calendar, players, player page and comparison, ranking with "why" breakdown, home | `src/features/{competitions,groups,calendar,players,ranking,home}/**`, `src/components/v2/**` | A (mocks) → B |
| **S4 Frontend: flows** | Result entry (sets/games), absence + substitute, Teams (pairs, divisions, results, standings), Shuffle admin, competition wizard, roster | `src/features/{results,teams,shuffle,admin}/**` | B |
| **S5 Platform & cleanup** | Port remaining v1 writes (cut-over critical path), editor on v2 models, legacy Jinja removal, chatbot schema, skills (`create-edition`, `start-next-edition`, `do-linear-ticket`), CSV tools, substitutes Excel import | `modules/editor.py`, `modules/*.py` (legacy), `templates/**`, `core/**`, `.claude/skills/**`, `services/imports/**` | B (writes first) |
| **S6 QA & parity** | Semantic parity v1↔v2 per page, Playwright e2e smoke, visual diff old vs new pages, migration rehearsals | `scripts/parity/**`, `e2e/**`, `docs/v2/qa/**` | A |

All sessions start now. Until S0 publishes `docs/v2/api/openapi.yaml` and the Postgres test template on `v2/integration`, build against the draft in section 4 and pull from `v2/integration` as soon as S0 announces G0.

## 4. API v2 (draft for spec v0)

Principles: resources named after the model; camelCase JSON; ids preserved; numbers unrounded (frontend rounds for display); GET never writes; errors `{error, code}`; auth = JWT (access 30 min + refresh 30 days); roles `player | admin | super_admin`.

Reads:
- `GET /seasons`, `GET /competitions?season&format`, `GET /competitions/{id}` (stages, groups, rules)
- `GET /groups/{id}` (members, standings, rounds), `GET /groups/{id}/matches?round`
- `GET /matches/{id}` (sets, participants incl. substitutes, absences)
- `GET /calendar?from&to&group`
- `GET /players`, `GET /players/{id}` (history from entries and awards), `GET /players/{id}/matches`, `GET /players/compare?a&b`
- `GET /rankings/current`, `GET /rankings/{snapshotId}`, `GET /rankings/players/{id}` (contribution per event)

Writes:
- `PUT /matches/{id}/result` (games or 3 set results for Teams), `POST /rounds/{id}/absences` `{playerId, substituteId?}`, `DELETE /absences/{id}`
- `POST /groups/{id}/close` (admin)
- Competitions (admin): `POST /competitions` (Clássica from previous via promotion, Shuffle, Teams), `POST /competitions/{id}/fixtures`, Shuffle `POST|DELETE /competitions/{id}/rounds`
- Teams: `GET|POST|DELETE /competitions/{id}/partner-requests`, `POST /competitions/{id}/pairs/close`, `POST /stages/{id}/divisions`

## 4b. Frontend navigation (Pedro, 2026-10-15)

- Tonight's goal: **everything running locally on the new database**; deploy decision tomorrow morning.
- **Shuffle and Teams lose their own nav tabs.** Everything lives under **Torneios**.
- Tournaments list: one card per competition (like today's tournament cards) with a format badge (Clássica / Teams / Shuffle / Super Cup), grouped by season, current season first. Accepted alternative: 4 cards, one per format, each opening its competitions.
- Each card opens the competition page; Teams and Shuffle pages are competition pages reachable from the list.
- Old `/shuffle` and `/teams` redirect to the current competition of that format; `/tournaments/:id` redirects to `/groups/:id`.
- Data: `GET /competitions?season&format` returns format, season, status (`upcoming | live | ended`), dates, group count and a cover image per competition: enough to render the cards.

## 5. Acceptance

- **Semantic parity (S6):** for every group/player/ranking, v2 numbers equal v1 compat output except listed intended differences.
- **Contract:** every v2 response validates against `openapi.yaml`.
- **Domain:** Teams reference case (P1 534 … P5/P6 100), 3-set invariant, Shuffle curve table, ranking rule examples.
- **E2E:** login + renewal, result entry, absence + substitute, Teams pair choice, ranking page, on desktop and phone width.
- A page is "done" only when parity, contract and e2e pass for it.

## 6. Conventions for every session

- Work in your own worktree and branch from `v2/integration`; small PRs into it; S0 merges. Never push to `master`.
- Only S0 writes alembic revisions, `models/v2.py`, the spec and generated types.
- Databases: always `${TEST_DB_PREFIX}_*`; never touch another prefix; never connect to production (35.205.246.86).
- Ports: S1 none, S2 5061, S3 8081, S4 8082/5062, S5 5063, S6 5064/8084.
- Bash: chain related steps with `&&`. Interactive commands in detached tmux.
- GitHub: `gh auth switch -u pedropacheco95` before any write, switch back after. No push or PR without Pedro's approval.
- OpenWolf: read `.wolf/cerebrum.md` first; log to `.wolf/memory.md` / `buglog.json`.
- Never ask Pedro for secrets.
- Report to S0 with SendMessage when blocked or done.
