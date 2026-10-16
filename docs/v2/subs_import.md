# Importing the SUBS_ sheet (after launch, with Pedro's approval)

Fills the historic "Substituto" slots of editions 18ª–22ª with the people who
actually played. Inputs, all reviewed: the sheet as JSON, `subs_name_map.csv`,
`subs_row_decisions.csv`; duplicates in `subs_duplicates.csv`.

## What it writes

- `match_participants` rows with `role = 'substitute'`, no entry, in the free
  slot beside the partner. Standings, points and awards do not move: the v2
  standings and `compat.players_in_division` count members by entry. The run
  recomputes the live, published and v1 tables of every touched division before
  and after, and aborts if any changed.
- One `audit_events` row per filled absence (`entity = 'absence'`,
  `action = 'substitute_imported'`, with the sheet row and participant ids).
  Absences have no participant column, so this is the link.
- Players for the new outside subs, `status = 'external'`, each with a login
  (username = name without accents or spaces, the onboarding convention).
- Zema 21ª J3–J6 (`note` rows): history keeps Zema in the seat, so nothing
  changes in the matches; an `audit_events` row (`entity = 'entry'`,
  `action = 'substitute_note'`, `played_by_player_id`) records Zé Pedro Graça.

## Order

Prerequisites: the post-launch migrations `c6a1d9e4b2f7` (ranking_entries.source) and
`d7b2e5f8a3c6` (subs_window = ranking) are applied, and the code includes S1's 44a9e21
(`bootstrap-ranking` rewrites the snapshot when it differs from `compute()`; backend
integration 9d651cb).

```bash
# 1. Merges, each reviewed (dry run first). Ranking rows of the duplicate are dropped.
flask merge-players --from 110 --into 21  --dry-run   # Cuca
flask merge-players --from 92  --into 90  --dry-run   # António Maria ("To maria")
flask merge-players --from 112 --into 106 --dry-run   # Álvaro van Zeller
flask merge-players --from 95  --into 25  --dry-run   # Kiko CRBF
#    then without --dry-run. The ranking is rewritten after step 2 (92's 21ª now counts for 90).

# 2. The import.
flask import-substitutes subs.json docs/v2/subs_name_map.csv \
  --decisions docs/v2/subs_row_decisions.csv --dry-run
#    then without --dry-run, then:
flask v2 bootstrap-ranking   # rewrites the stored ranking + players.* mirror if it differs
```

```bash
# 3. Teams 2026/27 roster: João Mendonça (created by step 2 as external) replaces Miguel Lemos (91).
flask swap-roster-player --competition 27 --out 91 --in-name "João Mendonça" --dry-run
#    then without --dry-run. Removes 91's entry and partner requests (v2 and teams_*), adds his entry,
#    sets his status to member (the schema has no 'active') and keeps/creates his login.
#    Refuses if 91 is already in a group, pair, match, vacancy or award. Then:
flask v2 bootstrap-ranking   # again: without it the stored ranking and players.* miss Mendonça
```

Every command is one transaction; `--dry-run` rolls back. Rows imported with a
points mismatch carry `points_mismatch: true` in their audit row.

## Before running on production

- **Wait for S2's profile fix** (member stats filter `role = 'member'`, subs shown separately; external
  players filtered out of the lists). Then re-diff profiles on a clone: only the substitute counts may move.
- **Player profiles do change** (before S2's fix). The dry run's check covers standings (live, published, v1 division
  views, Shuffle overall) and they are unchanged, but `/api/v1/players/<id>` and `/api/v2/players/<id>`
  count every `match_participants` row, so an existing player who also subbed gains matches played,
  wins, games and attendance (78 of 182 profile responses changed on the clone; v1 attendance reaches
  107% and matchweeksMissed −1). Decide whether sub appearances count, and filter `role = 'member'` in
  those stats if not, before importing.

- `/api/v1/players` and `/api/v2/players` list every player, so the 70
  external subs would appear in the public players list. Filter
  `status = 'external'` there first (or accept it).
- Back up first.
