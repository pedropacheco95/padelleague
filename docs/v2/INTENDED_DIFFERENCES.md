# Intended differences: v2 vs the pre-v2 app

The parity harness (`scripts/parity/`) treats everything not listed here as a regression.

| Id | What changes | Why |
|---|---|---|
| D1 | Matches 85 and 86 (2022-03-09) appear in division 3, jornada 1: in its tournament page, the calendar, and the division 3 history of players 8, 12, 13 and 16 (+2 played, +2 won, +40 computed points for 8 and 12). | Their `division_id` was lost. The stored division 3 standings already counted them; the matches were simply invisible. |
| D2 | After a result is edited, a division's match lists keep their original order, and "last played matches" picks the same tied matches as before the edit. | The old tables had no keys, so an UPDATE moved the edited row to the end of the physical order, which reshuffled lists. |
| D3 | GET requests never write. Pages show the same values, but opening a tournament, the ranking or the shuffle no longer rewrites places, stats or rankings in the database. | Reads that wrote caused the 2026-09-30 place changes. |
| D4 | Ending a division counts that division in the ranking recompute it triggers. | Bug B1: the old code recomputed before marking the division ended. |
| D5 | The chatbot's SQL runs in a read-only transaction on its own connection, with the old table names resolving to the `compat` views. A generated UPDATE or DELETE is rejected instead of committed. | The model-generated SQL used to share the app session, and `log_question` committed it. |
| D6 | GET routes that delete or create (`/tournaments/delete/<id>`, `/editions/delete/<id>`, the legacy `/api/delete*` on GET...) raise an error instead of deleting. `/players/ranking/recalculate` and the sponsor-click redirect still write. | Deletes on plain GET could be triggered by any link or image tag. |

| D7 | Division 69 places follow the computed order: player 38 goes 3º → 6º, player 52 4º → 3º, player 86 6º → 4º. This affects their player history and ranking points. | Pedro (2026-10-14): the computed order wins over the manual override. Applied to every finished division; only 69 differs. |

## Approved, not yet applied

- **Ranking rule.** The site shows "last 4 editions by id" (Shuffle excluded). The settled 2026/27 rule is "last 3 completed + current". Approved by Pedro on 2026-10-14; it will be applied as a listed change before Teams seeding.
