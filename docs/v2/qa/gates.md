# Release gates: reading rules (written before the results)

Owner: S6. Each check below has its reading rule fixed **before** it is run, so a
result cannot be argued into a pass afterwards. A rule changes only by a commit to
this file that says why, made before the run it applies to.

Go/no-go: 16 Oct 08:00, S0 with Pedro (`APP_MIGRATION_PLAN.md` §0). S6 may stop the
release at any hour; a stop names the check and the evidence.

## R1. Read parity (urls.json, ~530 requests)

Golden = `feature/teams-pairs` code on the backup + `a1d5c0e7b3f2`.
Candidate = `v2/integration` code on the same backup migrated to head.
Both captured by S6 on `s6_*` databases, clock frozen, same request list.

- **Green:** `requests compared` equals the golden file count, `missing in candidate: 0`,
  `regressions: 0`; every "expected" line names an id listed in `INTENDED_DIFFERENCES.md`
  (D1, D2, D7, D8, …), and the requests counted under each id are the ones that id
  describes (spot-check: open one file per id).
- **Red (stop):** any regression, any missing request, any non-2xx status that was 2xx
  in golden, or a request count lower than golden. One regression is enough.
- **Surprising outcome — zero expected differences:** red until explained. D1 and D8
  must show up on a backup that contains matches 85/86 and Teams rows; if they do not,
  the candidate likely ran on the wrong database or the golden is the candidate.
- **Surprising outcome — golden differs from itself:** capture golden twice; if two
  golden runs differ, the harness is non-deterministic there and that key is reported as
  "unstable" (not green, not red) and listed for S0; it may not hide a candidate change.

## R2. Write parity (scenarios.json)

- **Green:** every scenario has the same per-step status codes as golden and no
  regression outside listed differences (D2 sorting is normalised in `diff.py`).
- **Red:** any status change, or any body difference not listed.
- **Surprising:** a write that returns 2xx in golden but blocked (`CompatWriteError`,
  4xx/5xx) in candidate is red even if the follow-up reads match: v1 must keep serving
  every write after the DB cut-over.

## R3. verify_migration.sh on a fresh backup

- **Green:** every table `legacy-only=0 compat-only=0` / `changed-or-missing=0`, except
  `matches` (D1: exactly 2 rows each side, ids 85 and 86) and `players_in_division`
  (D7: exactly 3 rows each side, division 69, players 38/52/86).
- **Red:** any other non-zero count, or the D1/D7 counts differing from 2 and 3.
- **Surprising:** D1/D7 counts of 0 — means the fix did not apply or the view
  hides it; red until explained.

## R4. Cut-over rehearsal (`scripts/parity/rehearse_cutover.sh`)

- **Green:** restore → upgrade to head → R3 green → smoke green → rollback restores a
  database whose row counts and `alembic_version` equal the pre-migration copy; every
  step timed; total migration + verify window ≤ 15 min on this machine.
- **Red:** any step fails, rollback leaves a different database, or the upgrade needs a
  manual step not in `cutover.md`.
- **Surprising:** the upgrade is much faster/slower (>3×) than the previous rehearsal —
  re-check that the source backup is the expected one (row counts) before reading it.
- Gate G2 needs **two** consecutive green rehearsals on the morning's backup.

## R5. E2E smoke (Playwright, desktop + 375px)

- **Green:** all specs pass on both viewports, retries = 0.
- **Red:** any failure, or a pass that needed a retry (flake counts as red for the gate,
  then gets investigated).
- **Surprising:** all specs pass on a candidate where R1 is red — the specs are not
  covering what the parity diff found; record which page and add an assertion.

## R6. Semantic parity v1 ↔ v2 (per page, Phase 3)

- **Green:** for every mapped field, v2 value == v1 value (numbers compared unrounded on
  the v2 side, v1 rounding applied before comparing); unmapped v1 fields listed.
- **Red:** any mismatch not listed in `INTENDED_DIFFERENCES.md`.
- **Surprising:** a v1 field with no v2 counterpart that the page renders — red for that
  page's switch until S2/S0 decide (map it or list it as intended).
