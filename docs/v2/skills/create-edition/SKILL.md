---
name: create-edition
description: Create the next edition of the Padel League — compute promotions and relegations from the last edition, slot in drop-outs and step-ins, then write the edition, its divisions, player assignments and full fixture list to production. Use when asked to "create the next edition", "criar a próxima edição", "set up the new season", "montar as divisões", or to redo an edition's fixtures.
---

# Create the next edition (v2 database)

<!-- v2 version (S5, 2026-10-15). Copy over .claude/skills/create-edition/SKILL.md at the
     database cut-over; before it, production still has the old tables. -->

Everything runs through two validated commands: `flask propose-edition` (promotion
from the last edition → a plan JSON) and `flask create-edition` (writes it).

Paths are relative to the project root (the outer `padelleague/` folder). The git
repo is the **nested** `padelleague/` directory.

## The data model, in one line

An edition is a `competitions` row (`format = 'classica'`) → one `stages` row
(number 1) → its divisions are `competition_groups` (`tier` 1 = 1ª Divisão, `rating`
2000, 1000, …) → each player has an `entries` row in the competition and a
`group_members` row in their division → `rounds` are the jornadas (shared by all
divisions of the stage) → `matches` + `match_sets` (score, set 1) +
`match_participants` (who played, `side` home/away). Finished divisions keep their
published table in `standing_snapshots`. Old names (`divisions`, `editions`,
`players_in_division`, `players_in_match`) no longer exist.

## The format is fixed — it constrains the whole plan

`padel_league/tools/games_order.json` is hardcoded to **8 players, 7 jornadas,
6 jogos per jornada**. Consequences you must respect:

- Every division is exactly 8 players. **Total players must be a multiple of 8**,
  and that number *determines* the division count. 44 players is not an edition.
- Each jornada has 4 fixed pairs playing a round-robin between them; over the 7
  jornadas every player partners every other exactly once, 21 jogos each.
- Ratings halve down the ladder: 2000, 1000, 500, 250, 125, 63…
- Courts follow the ladder: 1ª on Campos 1-2, 2ª on 3-4, … (derived, not configured).
- Jornadas are weekly from `beginning_datetime`; the edition ends on the 7th
  jornada (the service sets the end date itself — don't pass one).

## 1. Gather the inputs

Do not start without these. Ask for anything missing:

1. **The confirmed roster** — who's in, who's out, who's new. Nothing in the
   database records this; the `registrations` table is dead (17 rows, edition 3
   only). This is always input #1.
2. **Where each newcomer goes.** New players have no standings. By default they
   fill the vacancies from the bottom division up, in the order given; a newcomer
   can be placed straight into a division (e.g. a Golden Ticket into the 1ª).
   `players.ranking_points` can inform the suggestion, but the owner decides.
3. **Edition name** (e.g. "23ª Edição") and **division base name** (e.g. "Inverno 2027").
   Division names are `<Base> - Nª Divisão` and must be unique.
4. **Start date, weekday and hour** — e.g. Tuesdays 21:30 → `2027-01-12T21:30:00`.
5. **Confirm the promotion rule**: default is top 2 up, bottom 2 down at every
   boundary. Ask about exceptions before assuming.

## 2. Read the last edition

```sql
-- the last Clássica editions
select c.id, c.name, c.status, c.starts_on
from competitions c where c.format = 'classica'
order by c.starts_on desc nulls last, c.id desc limit 2;

-- its divisions
select g.id, g.tier, g.name, g.rating, g.has_ended, count(gm.id) as players
from competition_groups g
join stages st on st.id = g.stage_id
left join group_members gm on gm.group_id = g.id
where st.competition_id = <last_id>
group by g.id order by g.tier;

-- final standings (frozen at close-out)
select g.tier, ss.place, p.id, p.name, ss.points, ss.appearances
from standing_snapshots ss
join group_members gm on gm.id = ss.group_member_id
join competition_groups g on g.id = gm.group_id
join stages st on st.id = g.stage_id
join entries e on e.id = gm.entry_id
join players p on p.id = e.player_id
where st.competition_id = <last_id>
order by g.tier, ss.place;
```

Every division must have `has_ended = true` before rolling forward
(`propose-edition` refuses otherwise). Use raw `appearances` (max 21) if
attendance matters; `percentage_of_appearances` stores `appearances × 37.5`.

## 3. Propose the plan

```bash
cd padelleague
export POSTGRES_HOST=35.205.246.86
export POSTGRES_PW="$(awk -F: '$1=="35.205.246.86"{print $5}' ~/.pgpass)"
export ALLOW_REMOTE_DB=1

.venv/bin/flask --app app:run_app propose-edition \
  --previous <last_id> --name "23ª Edição" --start 2027-01-12T21:30:00 \
  --prefix "Inverno 2027" \
  --withdrawals 12,40 --new 131,132 \
  [--placed '{"1": [133]}'] [--season 2026/27] [--event-slot classica-2] \
  --out <scratchpad>/plan.json
```

It reads only. It applies the promotion rule to the frozen standings, cascades the
withdrawals, fills vacancies with the newcomers and prints a `note:` line for
anything that does not add up (a short division, a leftover newcomer). Fix the
inputs until there are no notes.

The plan it writes:

```json
{
  "edition_name": "23ª Edição",
  "beginning_datetime": "2027-01-12T21:30:00",
  "divisions": [
    {"name": "Inverno 2027 - 1ª Divisão", "rating": 2000, "players": [45, 27, 28, 18, 32, 16, 13, 7]}
  ]
}
```

`players` is in seeding order. It does **not** decide partnerships — the draw is
random per division, by design. Optional keys: `season` (name; default = the
season containing the start date) and `event_slot` (`classica-1|2|3`; never guessed).

## 4. Get approval — hard gate

Show the owner the full layout as a readable table, naming every player and marking
who went up (↑), down (↓), left, or joined. **Wait for explicit approval before
writing anything.** This creates a public season.

## 5. Dry run, then apply

```bash
.venv/bin/flask --app app:run_app create-edition --plan <plan.json> --dry-run
```

Dry run only reads. It checks the edition name is free, every division name is
free, each division has 8 distinct players, no player is in two divisions, every
player id exists, and a season contains the start date. Fix whatever it names, then
drop `--dry-run`.

The real run is one transaction: competition, stage, rounds, divisions, entries,
members and all fixtures, or nothing. It prints the seat → player draw per
division — **keep that output**, it is not recoverable afterwards (it is also in
`audit_events`, action `fixtures_generated`).

To redo one division's fixtures (only before any jogo is played):

```bash
.venv/bin/flask --app app:run_app generate-fixtures --division-id <group_id> --force
```

## 6. Verify

```sql
select g.name, g.tier, g.rating, g.starts_at, g.end_date,
       (select count(*) from group_members gm where gm.group_id = g.id) as players,
       (select count(*) from matches m where m.group_id = g.id) as matches
from competition_groups g
join stages st on st.id = g.stage_id
where st.competition_id = <new_id>
order by g.tier;
```

Expect 8 players and 42 matches per division. Then confirm every match has 4
players:

```sql
select count(*) from (
  select m.id from matches m
  join competition_groups g on g.id = m.group_id
  join stages st on st.id = g.stage_id
  left join match_participants mp on mp.match_id = m.id
  where st.competition_id = <new_id>
  group by m.id having count(mp.id) <> 4
) x;
```

Must be 0. (In *past* editions this count is high — before v2, absences were
recorded by removing the player from the jogo. For a brand-new edition it must be 0.)

## 7. If it goes wrong

The create is transactional, so a failure leaves nothing behind. To undo a
*completed* edition before any jogo is played (matches first: participants point at
the entries the competition delete would cascade):

```sql
begin;
delete from matches where group_id in (
  select g.id from competition_groups g
  join stages st on st.id = g.stage_id
  where st.competition_id = <id>);
delete from competitions where id = <id>;   -- stages, rounds, groups, entries, members cascade
commit;
```

Confirm with the owner before running any of that. Never on an edition with played
jogos or awards.

## Notes

- The React admin can do the same through the API: `POST /api/v2/competitions/preview`
  and `POST /api/v2/competitions` (same services), or the older
  `/edition/create_divisions` page (`POST|PUT /api/v1/divisions`, all admin-JWT).
- Editing a division after it has ended only allows renames and images; players
  are changed with the editor's *Substituir jogador* action.
- `POSTGRES_HOST` decides the database. Outside production the app refuses a
  non-localhost host unless `ALLOW_REMOTE_DB=1`.
