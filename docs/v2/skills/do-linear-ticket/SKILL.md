---
name: do-linear-ticket
description: Fetch a not-done user-request ticket from Linear (Porto Padel League) and resolve it — production DB data fixes via psql, code changes via branch + PR, status updates and comments back on the ticket. Use when asked to "do a ticket", "work the next ticket", "pick up a Linear ticket", "process ticket POR-N", or "fix what's in Linear".
---

# Do a Linear Ticket (v2 database)

<!-- v2 version (S5, 2026-10-15). Copy over .claude/skills/do-linear-ticket/SKILL.md at the
     database cut-over; before it, production still has the old tables. -->

Tickets are user-side requests for the Padel League Porto app. Each one is either
a **production DB data fix** (wrong name, missing game result, etc.), a **code
change**, or **too uncertain to act** — classify first, then follow that path.

Provenance: this workflow was defined by the repo owner (Pedro), who explicitly
authorized direct production data fixes for user-request tickets because the DB
is backed up daily. Anything beyond a well-understood data fix must go through
a PR or a clarifying comment instead.

Paths are relative to the project root (the outer `padelleague/` folder).
The git repo is the **nested** `padelleague/` directory (GitHub
`pedropacheco95/padelleague`, default branch `master`). The React frontend
`padel_league_frontend/` is its own separate git repo. The outer folder is not
a repo — always `git -C padelleague ...` or `cd` in first.

## 1. Fetch the ticket

Use the `linear-server` MCP tools (already configured for this project):

- Next ticket: `list_issues` with `team: "Porto Padel League"`, `state: "Todo"`
  (also check `"Backlog"` if Todo is empty). Skip tickets already `In Progress`.
- Specific ticket: `get_issue` with the identifier (e.g. `POR-5`). It returns
  the full description and a `gitBranchName` — use that branch name for code changes.
- Team states are exactly: `Backlog`, `Todo`, `In Progress`, `Done`, `Canceled`,
  `Duplicate`. **There is no "In Review" state** — code-change tickets stay in
  `In Progress` after the PR is opened (owner's decision).

Immediately move the ticket to `In Progress` (`save_issue` with `id` + `state`)
so nobody else picks it up.

## 2. Classify

- Mentions wrong/missing **data** (a name, a score, a missed game, a ranking) and
  needs no behavior change → **DB fix**.
- Requires changed behavior, UI, or logic → **code change**.
- Ambiguous ask, conflicting info, or a destructive operation (DELETEs, bulk
  changes, anything you can't precisely verify) → **uncertain**: comment and
  stop (section 5). When in doubt, prefer this path.

## 3. DB fix path

Production Postgres — connection verified from this machine:

```bash
psql -U padel_user -h 35.205.246.86 -p 5432 -d padel_league -Atc "select 1;"
```

Credentials are read from `~/.pgpass` (standard Postgres mechanism; the password
is the one used in `padelleague/scripts/backup.sh`). Daily backups land in
`gs://portopadelleague-storage/db_backups`.

Workflow:

1. Read the relevant model in `padelleague/padel_league/models/` (check
   `.wolf/anatomy.md` first) to understand column semantics before touching data.
2. `SELECT` the exact rows first — confirm you match precisely what the ticket
   describes, and record the before values.
3. Apply the change in a transaction with a verification select:
   `BEGIN; UPDATE ...; SELECT ...; COMMIT;` — roll back if the select looks wrong.
   Only single, precisely-scoped UPDATEs/INSERTs; never DELETE or bulk-update
   without going through the uncertain path.
4. Comment on the ticket (`save_comment`) with the **exact SQL executed** and
   before/after values, so a dev can audit or reverse it.
5. Move the ticket to `Done` (`save_issue`).

Key tables (v2 model; the old `divisions`, `editions`, `players_in_division`,
`players_in_match` names no longer exist):

| Portuguese | Table | Notes |
|---|---|---|
| Jogador | `players` (name, full_name, ranking_points, ranking_position) | + `users` (username, email, role, player_id) for the login |
| Edição | `competitions` (`format = 'classica'`, name, status) | Shuffle/Teams are competitions too (`format`) |
| Divisão | `competition_groups` (name, tier, rating, has_ended) via `stages.competition_id` | |
| Jornada | `rounds` (stage_id, number, date) | shared by all divisions of the stage |
| Inscrição | `entries` (competition_id, player_id, status, final_place) + `group_members` (group_id, entry_id) | |
| Jogo | `matches` (group_id, round_id, scheduled_at, court, status 'scheduled'/'played') | score in `match_sets` (match_id, set_no = 1, home_games, away_games) |
| Quem jogou | `match_participants` (match_id, side 'home'/'away', slot 1/2, role 'member'/'substitute', entry_id, player_id) | |
| Falta | `absences` (entry_id, round_id) | |
| Classificação final | `standing_snapshots` (group_member_id, place, points, …) | frozen when a division ends |
| Pontos de ranking | `awards` (group_id, player_id, place_points, bonus_points) | |

Domain is Portuguese: Divisão=division, Jornada=matchweek, Jogo=match, Jogador=player.

**Results and absences are not raw-SQL fixes on v2.** Standings, awards and the
ranking are derived from the match facts, and a finished division's table is frozen;
a bare `UPDATE match_sets` leaves the published table, awards and ranking stale. Use
the app's own write path, which records an `audit_events` row:

- the admin result screen (React, any logged-in admin), or
- the service from a Flask shell against production, in one transaction:

```bash
cd padelleague
export POSTGRES_HOST=35.205.246.86
export POSTGRES_PW="$(awk -F: '$1=="35.205.246.86"{print $5}' ~/.pgpass)"
export ALLOW_REMOTE_DB=1
.venv/bin/flask --app app:run_app shell
```

```python
from padel_league.sql_db import db
from padel_league.services import results, closeout
m = results.record_result(<match_id>, <home_games>, <away_games>, actor_user_id=1)
db.session.flush()
if m.group.has_ended:
    closeout.refresh_closed_group(m.group_id, actor_user_id=1)   # re-snapshot, awards, ranking
db.session.commit()
```

Plain attribute fixes (a player's name, a court, a date) remain single scoped
UPDATEs as above. Swapping a player in a division is the editor's
*Substituir jogador* action, never SQL.

## 4. Code change path

1. In the nested repo: `git -C padelleague fetch origin master` and branch off
   `origin/master` using the ticket's `gitBranchName`
   (e.g. `pedropachecocontas/por-5-fix-thing`).
2. Implement (delegate to a subagent for non-trivial work), run relevant checks,
   commit, push.
3. Open the PR: `gh pr create --base master --title "POR-N: <title>" --body "..."`
   (run from inside `padelleague/`; `gh` is authenticated as pedropacheco95).
   Include the ticket URL in the body — Linear's GitHub integration links it.
4. `save_issue` → state `In Progress`, and `save_comment` with the PR link and a
   summary of the change. Do **not** move to Done; a human merges first.

Frontend-only changes happen in `padel_league_frontend/` (separate repo, same flow).

## 5. Uncertain path

Leave a comment (`save_comment`) stating precisely what is unclear and what
information would unblock it, tagging the ticket creator. Leave the ticket in
`Todo`.

**Gotcha — `get_issue` does not return the creator.** To find who to tag:
check `list_comments` on the issue for the author, or use the assignee. If
neither identifies them, tag the workspace admins: `@pedropachecocontas` (Pedro)
or `@dpssbf.95` (Dudas). Mentions use `@displayName` (values from `list_users`).

## Wrap-up (every ticket)

Follow project OpenWolf rules: append what was done to `.wolf/memory.md`; if a
DB fix revealed a data quirk or a code change revealed a convention, add it to
`.wolf/cerebrum.md`.
