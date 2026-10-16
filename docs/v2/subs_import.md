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

```bash
# 1. Merges, each reviewed (dry run first). Ranking rows of the duplicate are dropped.
flask merge-players --from 110 --into 21  --dry-run   # Cuca
flask merge-players --from 92  --into 90  --dry-run   # António Maria ("To maria")
flask merge-players --from 112 --into 106 --dry-run   # Álvaro van Zeller
flask merge-players --from 95  --into 25  --dry-run   # Kiko CRBF
#    then without --dry-run; then recompute the ranking (92's 21ª now counts for 90).

# 2. The import.
flask import-substitutes subs.json docs/v2/subs_name_map.csv \
  --decisions docs/v2/subs_row_decisions.csv --dry-run
#    then without --dry-run.
```

Both commands are one transaction each; `--dry-run` rolls back.

## Before running on production

- `/api/v1/players` and `/api/v2/players` list every player, so the 70
  external subs would appear in the public players list. Filter
  `status = 'external'` there first (or accept it).
- Back up first.
