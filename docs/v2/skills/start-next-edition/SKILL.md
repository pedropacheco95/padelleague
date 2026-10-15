---
name: start-next-edition
description: Kick off a new Padel League edition end to end — open a Linear ticket asking Dinis for the roster and dates, then once he answers, build the divisions, generate the posters and banners with AI, and create the edition in production. Use when asked to "start the next edition", "começar a próxima edição", "ask Dinis for the edition info", "create this year's tournaments", or to check whether the edition ticket has been answered.
---

# Start the next edition (v2 database)

<!-- v2 version (S5, 2026-10-15). Copy over .claude/skills/start-next-edition/SKILL.md at
     the database cut-over; before it, production still has the old tables. -->

Two phases, usually days apart. Work out which one you are in **before doing
anything**: if a Linear ticket for the next edition already exists, you are in
phase 2.

Paths are relative to the project root (the outer `padelleague/` folder). The
mechanics of creating divisions live in [[create-edition]] — this skill is the
Linear front door and the artwork step around it. Read that skill too; do not
duplicate its rules here.

## The constraint that drives everything

`padel_league/tools/games_order.json` is hardcoded to **8 players, 7 jornadas,
6 jogos**. So the confirmed roster must be a **multiple of 8**, and that number
*determines* the division count. This is the single most common reason the
ticket has to go back to Dinis, so make it prominent in the ask.

## Phase 1 — open the ticket

Find the team and the assignee first; do not hardcode ids:

- `list_teams` → the Porto Padel League team
- `list_users` → find Dinis, match on name. **If more than one plausible match,
  stop and ask Pedro which one.** Assigning a season-blocking ticket to the
  wrong person costs days.

Read the last edition so the ticket can quote real names back at him — a list of
48 names to confirm is far easier to answer than "who's playing?":

```sql
with last as (
  select id from competitions where format = 'classica' and status = 'ended'
  order by starts_on desc nulls last, id desc limit 1)
select g.name as divisao, ss.place, p.id, p.name, ss.appearances
from standing_snapshots ss
join group_members gm on gm.id = ss.group_member_id
join competition_groups g on g.id = gm.group_id
join stages st on st.id = g.stage_id
join entries e on e.id = gm.entry_id
join players p on p.id = e.player_id
where st.competition_id = (select id from last)
order by g.tier, ss.place;
```

Create one issue, assigned to Dinis, titled like
`Informação para a 22ª Edição`. Body in **Portuguese** — Dinis is answering, and
the league's working language is Portuguese. Ask for exactly:

1. **Confirmação de jogadores** — paste last edition's 48 players grouped by
   division, and ask him to mark who is out and list anyone new. Say plainly
   that the total must be a multiple of 8, and ask for a waiting list if it
   isn't.
2. **Onde entram os jogadores novos** — new players have no standings, so he has
   to place them. Offer `players.ranking_points` as a hint if useful.
3. **Nome da edição** and **nome base das divisões** (e.g. "Inverno 2027").
   The number runs across every format (20ª = Shuffle, 22ª = Masters de Outono,
   23ª = Teams 2026/27), so propose `services.editions.next_edition_number()`
   (24ª as of 2026-10-15) and only ask whether he wants a suffix.
4. **Data de início, dia da semana e hora** (e.g. terças às 21:30).
5. **Confirmação da regra de subidas/descidas** — default 2 sobem / 2 descem.
6. **Campos** — Campo 1 / Campo 2 as usual?

Do **not** ask him for posters or banners. Those are generated (see phase 3).

Then tell Pedro the ticket number and stop. Do not poll Linear on a schedule
unless he asks.

## Phase 2 — when the ticket is answered

Re-read the issue and all its comments. Then:

1. **Validate the roster.** Count the confirmed players. If it is not a multiple
   of 8, comment on the ticket saying exactly how many you have and how many
   short/over, and stop. Do not guess who to add.
2. **Resolve every name to a player id before anything else.** This is where
   the real errors live. From the 22ª Edição:
   - *Fipas* was listed as withdrawing but has **played 0 editions** — he was
     never in the roster, so removing him changed nothing. Always check he has an
     entry in the last edition (`select 1 from entries where competition_id = <last>
     and player_id = <id>`) before counting someone as a withdrawal —
     `propose-edition` refuses unknown withdrawals.
   - *"Diogo"* is ambiguous: there is a **Diogo Leão** and a **Diogo Garrett**,
     both in the last edition. Confirm, never guess.
   - *"João Bello, Fipas"* — commas separate people, they are not a nickname.
     Confirmed by "João Lello, Zé Pedro Graça" being two people elsewhere in
     the same message.
   Query: `select id, name, full_name from players where name ilike '%x%' or
   full_name ilike '%x%'`.
3. **Build the layout** with `flask propose-edition` (see [[create-edition]]),
   which runs `services/classica_builder.next_classica_plan` → `services/promotion.py`
   on the frozen v2 standings. Do not hand-roll it — the rule is fiddly and it
   replays the real 21ª → 22ª exactly. Newcomers go in `--new` (bottom-up) or
   `--placed '{"<tier>": [ids]}'`.
4. **Create any genuinely new players first**, so the plan can reference their
   ids — with `padel_league/services/accounts.create_player(full_name)`, never a
   raw insert. **Every player must have a `users` row or they cannot log in.**
   It is idempotent, and it creates the login alongside the player: username =
   full name accent-stripped/no spaces/lower case, email `<username>@email.com`,
   password = the username. Verify afterwards with
   `flask backfill-player-accounts --dry-run` — it should report nothing
   missing. Hand the usernames to Dinis so players know their first login.
5. **Review the plan JSON** `propose-edition` wrote and dry-run it. See
   [[create-edition]] for the schema and the exact commands. Ratings come from the
   previous edition's divisions — 2000, 1000, 500, 250, 125, **63** (half up; if you
   ever edit them by hand use `int(x + 0.5)`, not `//` or `round()`).

Pedro chose **automatic creation**: once the dry run passes, create the edition
without waiting for his approval. That is a deliberate decision — but it only
applies when validation is clean. Anything ambiguous (a name you cannot match to
a player id, a roster that does not divide by 8, two people with the same first
name) is a stop-and-ask, not a guess.

## The promotion rule, in full

Base is 2 up / 2 down. Withdrawals are what make it hard.

A withdrawal leaves a hole in the division the player **would have been in next
edition**, not the one they were in — a 1º placer who leaves takes a slot out of
the division above, an 8º placer out of the division below.

Each hole is filled by stepping down a ladder of candidate pairs:

| holes remaining | candidates |
|---|---|
| 1st and 2nd | 7º of this division · 3º of the one below |
| 3rd and 4th | 8º of this division · 4º of the one below |
| …           | one place further out each time |

An **even** number of remaining holes takes both candidates; an **odd** number
takes whichever has more appearances last edition, tie broken on career
appearances. Either way the division below loses a player, so the hole cascades
downward — which is why holes end up at the bottom division, where the newcomers
go.

If both candidates in a pair are unavailable, the next pair down is tried. The
league's rule does not cover that; it came up immediately in the 22ª (both the
7º of the 4ª and the 3º of the 5ª had withdrawn) and Pedro accepted stepping
out. Flag it on the ticket whenever it fires.

Slots that an incoming player is already taking are passed with `--placed` so
they are not cascaded into.

## Phase 3 — artwork

Posters and banners are AI-generated. The league already does this by hand — the
posters in production carry a Grok watermark — so this is automating an existing
practice, not inventing one.

```bash
cd padelleague
export POSTGRES_HOST=35.205.246.86
export POSTGRES_PW="$(awk -F: '$1=="35.205.246.86"{print $5}' ~/.pgpass)"
export ALLOW_REMOTE_DB=1
export GCS_UPLOADS_BUCKET=portopadelleague-storage
export LLM_API_KEY=...        # same key production uses

.venv/bin/flask --app app:run_app generate-artwork --edition-id <competition_id>
```

Two images per division, both JPEG in `gs://portopadelleague-storage/Division/`:

| Field | Shown as | Size | Style |
|---|---|---|---|
| `logo_image_id` | Poster | **620 × 875** | photoreal padel + Porto skyline |
| `large_picture_id` | Ícone da cidade | **640 × 147** | flat illustration of a Porto landmark |

Notes that matter:

- The model cannot emit those exact ratios. Everything is cover-cropped to the
  exact pixel size by `services/artwork.normalise` — never stretched. Output
  reports `was_resized`, and the CLI prints how many were adjusted. **Look at
  the cropped results**; a bad centre-crop is the likely failure, not a crash.
- **No text in the artwork.** The site renders the division name itself, and
  image models render words badly. The prompts say so explicitly.
- Each division gets a different scene variation so an edition doesn't end up
  with six copies of one picture.
- Divisions that already have artwork are skipped unless you pass `--force`.
- Each image commits on its own — generation is slow and paid per image, so a
  failure on division 5 does not discard the first four. Re-run to fill gaps.

## Phase 4 — verify and report back

Run the verification queries from [[create-edition]] (8 players and 42 matches
per division, every match with exactly 4 players), then confirm the artwork
landed:

```sql
select g.name, g.logo_image_id, g.large_picture_id
from competition_groups g join stages st on st.id = g.stage_id
where st.competition_id = <id> order by g.tier;
```

No nulls. Then comment on the Linear ticket with what was created — edition id,
the division/player layout, and any images that had to be cropped — and move it
to Done. Tell Pedro here as well, with the seat → player draw from the fixture
output, which is not recoverable afterwards.

## Gotchas

- `.env.dev` points Flask at **localhost**. Always export `POSTGRES_HOST` (and
  `ALLOW_REMOTE_DB=1`, or the app refuses a remote host) before any `flask` command.
- Old table names (`editions`, `divisions`, `players_in_division`) are gone on v2:
  an edition is a `competitions` row (`format = 'classica'`), a division a
  `competition_groups` row. See [[create-edition]] for the model in one line.
- `registrations` is a dead table (17 rows, edition 3 only). It is not a roster.
- `percentage_of_appearances` is broken — it stores `appearances × 37.5`. Use
  raw `appearances` (max 21).
- Edition names (per format) and division names are both **unique** — the plan
  validation refuses duplicates.
- The edition name and the division base name need not match. The 22ª is
  "22ª Edição da Padel League : 1º Masters de Verão" while its divisions are
  "Masters de Outono - Nª Divisão".
- Keep the seat → player draw the CLI prints. It is random and stored nowhere.

## Worked example

The 22ª Edição (competition 25, created 2026-08-24) is the reference run: 48
players, 6 withdrawals, 6 arrivals, start 2026-09-01 21:30, Campos 1-12. Its
expected layout is pinned in `padel_league/tests/test_promotion.py`, and the
21ª → 22ª replay in `padel_league/tests/domain/test_classica_builder.py`.
