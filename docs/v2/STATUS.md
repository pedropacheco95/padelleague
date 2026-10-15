# v2 migration — status board

Updated by S0. Sessions report to S0; S0 edits this file on `v2/integration`.

## Gate G0 — reached 2026-10-15

| Item | Where |
|---|---|
| Backend integration branch | `v2/integration` (worktree `padelleague-s0`) |
| Frontend integration branch | `v2/integration` (worktree `padel_league_frontend-s0`): origin/main + feature/teams-pairs + generated types |
| Migration chain | 9c2f1a7d4e21 → a1d5c0e7b3f2 (Teams pairs, old system) → b7d2e4c1a9f0 (v2 core) → c4f1a9e2b7d3 (Teams on v2) |
| Test template | `v2_template` = 2026-10-15 backup + full chain, verified. Rebuild: `scripts/v2/build_template.sh [backup.sql.gz \| source-db]` |
| Your test DB | pytest: fixture `pg` clones `v2_template` into `${TEST_DB_PREFIX}_pytest_<pid>` and rolls back each test. Manual: `createdb -h localhost -U postgres -T v2_template ${TEST_DB_PREFIX}_dev` |
| Factories | `padel_league/tests/factories.py` |
| API contract v0 | `docs/v2/api/openapi.yaml`; validate responses with `padel_league/tests/contract.py::assert_matches_spec` |
| TS types | frontend `src/api/v2/schema.d.ts` + aliases in `src/api/v2/index.ts`; regenerate `SPEC=<openapi.yaml> npm run gen:api` (S0 only) |
| Parity | 530/530 reads, 6/6 writes on the 2026-10-15 backup; differences only D1, D2, D8 |
| Tests | 250 passing (`TEST_DB_PREFIX=<you> .venv/bin/python -m pytest -q padel_league/tests`) |

## Sessions

| Session | State | Next / blockers |
|---|---|---|
| S0 coordinator | G0 done | Merge session PRs; cut-over runbook with S6 |
| S1 domain engine | working | — |
| S2 API v2 | working | Implement against openapi v0; ask S0 for spec changes |
| S3 frontend public | working | Tournaments list + nav (plan §4b) |
| S4 frontend flows | working | Teams/Shuffle as competition pages |
| S5 platform | working | Merge landed; legacy/v1 write ports unblocked |
| S6 QA & parity | working | Golden for 2026-10-15 at scratchpad parity1015; build semantic parity |

## Open items / TODO

- `teams_*` tables are unused after c4f1a9e2b7d3; drop them in phase 4.
- Teams pair choice runs on v2 (`services/teams_pairing.py`) behind `/api/v1/teams`; S2 adds the `/api/v2/competitions/{id}/...` routes from the spec and reuses the service.
- Competition 25 (22ª Edição, Clássica I 2026/27) is `ended` in the backup (all six divisions have `has_ended`).
- Users have no `role` column yet; S2's role guard needs one: request the migration from S0.
