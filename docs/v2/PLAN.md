# v2 data model: migration plan

Branch `feature/v2-data-model`. Design reference: `data-model-diagrams.html` (outer project dir) and the artifact https://claude.ai/artifact/XEFjpZQEyCnpeSTush7Jsj.

## Decisions (Pedro, 2026-10-14)

| Topic | Decision |
|---|---|
| Teams | Built on the new model |
| Scope | Migrate **all** existing data; nothing is lost |
| Verification | Local old code vs local new code on the **same** copy of prod data; every API response diffed automatically; then a visual pass against the deployed app |
| Behaviour | **Exact parity first**: the migrated app reproduces today's output, bugs included. Fixes land afterwards as separate, listed changes |
| Old tables | Moved untouched to a read-only `legacy` schema |
| Releases | **R1 (before 18 Oct):** new core, full migration, awards-based ranking, Teams. **R2:** Super Cup, Golden Ticket, cleanups |

## Local environment

- Source data: the daily GCS backup, restored to the local database `padel_league_baseline`. It is never served directly; it is only a template.
- Development refuses to start against a non-local database host (`_refuse_remote_db_outside_production`). The old config silently fell back to the production IP whenever `POSTGRES_HOST` was unset.
- Old code: a `git worktree` of `master`. New code: this branch.
- Nothing leaves the machine. The harness runs without a mail password or LLM key, with a fake GCS bucket name and a frozen clock (`2026-10-14 12:00`).

## Parity harness (`scripts/parity/`)

1. `build_urls.py` lists 526 read requests from the baseline ids: every division, player, calendar month, per-division month, edition, comparison pairs, the shuffle, the ranking, and `auth/me`.
2. `capture.py --code <checkout> --template <db> --out <dir>` recreates the run database from the template **before every request**, because several GETs write. It saves `{path, status, body}` per request.
3. The golden set is captured twice from the old code. Any difference between the two runs is non-determinism (unordered relationships), and the diff normalises it.
4. `diff.py` compares golden and new output after normalising, and reports each difference as either **expected** (listed in `INTENDED_DIFFERENCES.md`) or a **regression**.
5. Write scenarios (match edit, absence, refresh standings, shuffle edit) are replayed on both sides; the follow-up reads and the resulting database rows are diffed.

## Target schema (R1)

Core:
- **Hierarchy:** `league` → `season` (sporting year) → `competition` (instance; `event_slot_id` nullable for historic editions) → `stage` → `group`; `round`.
- **Participation:** `entry` (player in a competition), `group_member` (entry in a stage's group), `pair`, `partner_request`.
- **Play:** `match`, `match_set`, `match_participant`, `absence`.
- **Frozen results:** `standing_snapshot`, which stores the full stored standings row for every ended group.
- **Ranking:** `award_event`, `award`, `ranking_rule`, `ranking_snapshot`, `ranking_entry`, `ranking_slot_value`.
- **People:** `player` (+ `status`), `user` (unique `player_id`, `role`), `audit_event`.

The non-competition tables keep their shape but gain real primary and foreign keys: `news`, `sponsors`, `sponsor_clicks`, `chatbot_logs`, `backend_app`, the shop tables, `registrations` and `images`.

### Changes driven by the data audit

- **Participants.** History never recorded substitutes: absent members' rows were deleted, leaving 2256 empty slots in 1707 of 3192 matches.
  - A slot's occupant is now an **entry**, a **known substitute player**, or **unknown**. Unknown is all that history has, and it renders as "Substituto".
  - Absence is stored separately, per entry per round (`absence.kind = full | partial`, `source = derived | recorded`).
  - Historic absences are derived (740 player-weeks plus partial weeks). Absentees are **not** pinned to specific historic slots, because that would be inference, not data.
  - From R1 on, marking a player absent writes a `recorded` absence plus an audit event. Substitutes are recorded as players.
- **Standings.** Ended groups keep their **entire stored row** in `standing_snapshot`: place, points, W/D/L, games, appearances, the raw `percentage_of_appearances` and `matchweek`. 70 stored rows have home/away-swapped game totals and division 69 has a manual place override, so a recompute would not reproduce them. Live groups use the computed view.
- **Ids are preserved** for players, users (the JWT identity), editions (now competitions), divisions (now groups) and league matches.
  - Shuffle matches 1–360 collide with league match ids, so they get new ids and keep `legacy_id`.
  - Shuffle tie-break hashes keep using the old tournament id 1.
  - Sequences are reset above the highest copied id.
- **Constraints checked against the data before the DDL is written:**
  - Edition 1 has two parallel groups rated 1000, so `tier` is not unique per stage.
  - Matches 85 and 86 have no division. They are attached to division 3, matchweek 1; this is listed as an intended difference.
  - Matches with 0–1 participants (777, 1047, 2728, 2815, 3029 and the 0–3 walkovers) are kept as they are, with `status = played`.
  - Duplicate people (Cuca 21/110, Álvaro 106/112) are kept, so player names are not made unique yet.
  - `product_images.path` is the only image reference for products and is carried over.
- **Shuffle.** It becomes a competition in season 2025/26 with 10 stages of 6 groups. Each player's group per round is rebuilt from their matches. `division_number` is kept as the next-round placement, and `has_ended` stays false as stored. Round dates are unknown (null).
- **Seasons** run September to July and are assigned from each edition's first division date. Edition 25 (22ª) is **Clássica I 2026/27**.

## R1 work order

1. ✅ Safety guard, branch, baseline database, parity harness.
2. ✅ Golden capture (526 reads, captured twice, deterministic apart from one list order) and 6 write scenarios.
3. ✅ Migration (`b7d2e4c1a9f0`, `migrations/sql/`) through `flask db upgrade`. Verified lossless: every legacy row is reproduced column for column (`scripts/v2/verify_migration.sh`).
4. ✅ Reads go through `compat` views over the v2 tables; GETs are read-only (`read_only.py`). **Parity: 526/526 reads and 6/6 write scenarios match**, apart from D1 and D2 (`INTENDED_DIFFERENCES.md`).
5. ◐ Write paths. Done: match result, absence (now recorded, optional substitute), refresh standings, shuffle score, division close-out with awards. To do: the shuffle admin actions, division create/update, fixture generation, the `create-edition` CLI, the editor swap/readd helpers and generic CRUD, and the legacy Jinja writes.
6. The chatbot schema prompt points at read-only views.
7. Parity run until the only differences are the listed intended ones.
8. Ranking: awards backfilled from history; switch to the settled 2026/27 rule (last 3 completed + current) as a **listed change**, then recompute.
9. Teams (needs the Estatutos spec and the reference test case).
10. Deploy plan: backup, migration run, smoke test, rollback path (`legacy` schema plus the backup).

## Open questions for Pedro

- The Teams Estatutos and the reference test case.
- Division 69's manual place override: keep it? Opening that page on prod today re-sorts it and destroys the override.
- Whether to fold the security lockdown (unauthenticated writes) into R1.
