-- v2 core data model: archive, create, copy, verify-ready.
--
-- 1. Every existing table is copied untouched into schema `legacy`.
-- 2. New competition tables are created in `public`.
-- 3. All competition data is copied across, keeping public ids.
-- 4. Old competition tables are dropped from `public` (their copies stay in `legacy`).
-- 5. Tables that keep their shape (players, users, news, shop...) get real keys.
-- 6. Schema `compat` exposes the old table shapes as views over the new tables,
--    so existing read code keeps producing identical output during the transition.
--
-- Runs inside one transaction (Alembic). Verification lives in scripts/v2/verify_migration.py.

------------------------------------------------------------------------------
-- 0. Preconditions: the data this script was written against (backup of
--    2026-10-14). If production has moved on in a way the script does not
--    handle, stop instead of guessing.
------------------------------------------------------------------------------
DO $$
DECLARE n bigint; ids text;
BEGIN
  SELECT count(*) INTO n FROM leagues;
  IF n <> 1 THEN RAISE EXCEPTION 'v2: expected exactly 1 league, found %', n; END IF;

  SELECT string_agg(id::text, ',' ORDER BY id) INTO ids FROM matches WHERE division_id IS NULL;
  IF coalesce(ids, '') <> '85,86' THEN
    RAISE EXCEPTION 'v2: matches without a division are %, expected 85,86 (they are attached to division 3)', ids;
  END IF;

  SELECT max(id) INTO n FROM editions;
  IF n <> 25 THEN
    RAISE EXCEPTION 'v2: latest edition id is %, expected 25 (the 22ª Edição = Clássica I 2026/27). Map new editions to event slots before migrating.', n;
  END IF;

  SELECT count(*) INTO n FROM shuffle_tournaments;
  IF n <> 1 THEN RAISE EXCEPTION 'v2: expected exactly 1 shuffle tournament, found % (season assignment is hard-coded)', n; END IF;

  SELECT count(*) INTO n FROM (SELECT match_id, player_id FROM players_in_match GROUP BY 1, 2 HAVING count(*) > 1) x;
  IF n > 0 THEN RAISE EXCEPTION 'v2: % players appear twice in the same match', n; END IF;

  SELECT count(*) INTO n FROM (SELECT player_id, division_id FROM players_in_division GROUP BY 1, 2 HAVING count(*) > 1) x;
  IF n > 0 THEN RAISE EXCEPTION 'v2: % duplicate player/division rows', n; END IF;

  SELECT count(*) INTO n FROM divisions WHERE rating NOT IN (2000, 1000, 500, 250, 125, 63);
  IF n > 0 THEN RAISE EXCEPTION 'v2: % divisions have a rating outside the 2000..63 ladder (tier mapping)', n; END IF;
END $$;

------------------------------------------------------------------------------
-- 1. Archive
------------------------------------------------------------------------------
CREATE SCHEMA legacy;

DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'
  LOOP
    EXECUTE format('CREATE TABLE legacy.%I AS TABLE public.%I', t, t);
  END LOOP;
END $$;

------------------------------------------------------------------------------
-- 2. New competition tables
------------------------------------------------------------------------------
ALTER TABLE leagues ALTER COLUMN id SET NOT NULL;
ALTER TABLE leagues ADD PRIMARY KEY (id);

CREATE TABLE ranking_rules (
  id              serial PRIMARY KEY,
  key             text NOT NULL UNIQUE,
  name            text NOT NULL,
  mode            text NOT NULL CHECK (mode IN ('last_n_by_id', 'last_n_completed_plus_current', 'per_slot')),
  last_n          integer,
  decay           double precision NOT NULL DEFAULT 0.75,
  win_bonus_divisor  double precision NOT NULL DEFAULT 100,
  draw_bonus_divisor double precision NOT NULL DEFAULT 250,
  options         jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at      timestamp NOT NULL DEFAULT now()
);

CREATE TABLE seasons (
  id              serial PRIMARY KEY,
  league_id       bigint NOT NULL REFERENCES leagues(id),
  name            text NOT NULL,
  starts_on       date,
  ends_on         date,
  ranking_rule_id integer REFERENCES ranking_rules(id),
  UNIQUE (league_id, name)
);

CREATE TABLE event_slots (
  id                 serial PRIMARY KEY,
  league_id          bigint NOT NULL REFERENCES leagues(id),
  key                text NOT NULL UNIQUE,
  name               text NOT NULL,
  format             text NOT NULL,
  holds_ranking_slot boolean,            -- NULL = not decided (Super Cup)
  calendar_order     integer NOT NULL
);

CREATE TABLE competitions (
  id                    bigserial PRIMARY KEY,   -- old edition ids are kept
  season_id             integer NOT NULL REFERENCES seasons(id),
  event_slot_id         integer REFERENCES event_slots(id),
  name                  text,
  format                text NOT NULL CHECK (format IN ('classica', 'shuffle', 'teams', 'super_cup')),
  status                text NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'running', 'ended')),
  starts_on             date,
  ends_on               date,
  rules                 jsonb NOT NULL DEFAULT '{}'::jsonb,
  counts_for_attendance boolean NOT NULL DEFAULT true,
  legacy_shuffle_id     integer UNIQUE,     -- shuffle_tournaments.id for migrated shuffles
  legacy_ord            bigint,             -- storage order of the pre-v2 row (old code relied on it)
  title                 text,               -- shuffle display title
  created_at            timestamp NOT NULL DEFAULT now(),
  updated_at            timestamp NOT NULL DEFAULT now()
);

CREATE TABLE ranking_snapshots (
  id                    serial PRIMARY KEY,
  league_id             bigint NOT NULL REFERENCES leagues(id),
  rule_id               integer NOT NULL REFERENCES ranking_rules(id),
  after_award_event_id  integer,            -- FK added after award_events exists
  computed_at           timestamp NOT NULL DEFAULT now(),
  is_dry_run            boolean NOT NULL DEFAULT false,
  note                  text
);

CREATE TABLE stages (
  id               serial PRIMARY KEY,
  competition_id   bigint NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
  number           integer NOT NULL,
  name             text,
  seeding_method   text,
  seeded_from_id   integer REFERENCES ranking_snapshots(id),
  emits_award      boolean NOT NULL DEFAULT false,
  status           text NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'running', 'ended')),
  UNIQUE (competition_id, number)
);

CREATE TABLE competition_groups (
  id                   bigserial PRIMARY KEY,   -- old division ids are kept
  stage_id             integer NOT NULL REFERENCES stages(id) ON DELETE CASCADE,
  tier                 integer,                 -- not unique: edition 1 has two parallel groups
  name                 text,
  structure            text NOT NULL DEFAULT 'round_robin' CHECK (structure IN ('round_robin', 'bracket')),
  rating               bigint,
  multiplier           integer,
  starts_at            timestamp,               -- divisions.beginning_datetime
  end_date             timestamp,
  has_ended            boolean,
  open_division        boolean,
  standings_up_to_date boolean,
  logo_image_id        integer REFERENCES images(id) ON DELETE SET NULL,
  large_picture_id     integer REFERENCES images(id) ON DELETE SET NULL,
  legacy_ord           bigint
);

CREATE TABLE rounds (
  id        serial PRIMARY KEY,
  stage_id  integer NOT NULL REFERENCES stages(id) ON DELETE CASCADE,
  number    integer NOT NULL,                   -- jornada number within the competition
  date      date,
  UNIQUE (stage_id, number)
);

CREATE TABLE entries (
  id              serial PRIMARY KEY,
  competition_id  bigint NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
  player_id       bigint NOT NULL REFERENCES players(id),
  kind            text NOT NULL DEFAULT 'regular' CHECK (kind IN ('regular', 'wildcard')),
  status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'withdrawn', 'replaced')),
  seed            integer,
  final_place     integer,
  legacy_ord      bigint,
  created_at      timestamp NOT NULL DEFAULT now(),
  UNIQUE (competition_id, player_id)
);

CREATE TABLE pairs (
  id          serial PRIMARY KEY,
  stage_id    integer NOT NULL REFERENCES stages(id) ON DELETE CASCADE,
  entry_a_id  integer NOT NULL REFERENCES entries(id),
  entry_b_id  integer NOT NULL REFERENCES entries(id),
  formed_by   text NOT NULL CHECK (formed_by IN ('mutual', 'ranking', 'draw', 'rotation', 'manual')),
  CHECK (entry_a_id <> entry_b_id)
);

CREATE TABLE partner_requests (
  id             serial PRIMARY KEY,
  stage_id       integer NOT NULL REFERENCES stages(id) ON DELETE CASCADE,
  from_entry_id  integer NOT NULL REFERENCES entries(id),
  to_entry_id    integer NOT NULL REFERENCES entries(id),
  submitted_at   timestamp NOT NULL DEFAULT now(),
  UNIQUE (stage_id, from_entry_id)
);

CREATE TABLE group_members (
  id        bigserial PRIMARY KEY,              -- old players_in_division ids are kept
  group_id  bigint NOT NULL REFERENCES competition_groups(id) ON DELETE CASCADE,
  entry_id  integer NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
  seed      integer,
  pair_id   integer REFERENCES pairs(id),
  legacy_ord bigint,
  UNIQUE (group_id, entry_id)
);

-- The full stored standings row of a finished group (or of a whole-competition
-- table such as the shuffle). Kept exactly, including the values the old code
-- computed wrongly, because they are what the site showed.
CREATE TABLE standing_snapshots (
  id                         bigserial PRIMARY KEY,
  entry_id                   integer NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
  group_member_id            bigint UNIQUE REFERENCES group_members(id) ON DELETE CASCADE,
  place                      integer,
  points                     double precision,
  appearances                bigint,
  percentage_of_appearances  double precision,
  wins                       bigint,
  draws                      bigint,
  losses                     bigint,
  games_played               bigint,
  games_won                  bigint,
  games_lost                 bigint,
  matchweek                  bigint,
  next_division              integer,          -- shuffle: placement for the next round
  legacy_id                  integer,          -- players_in_shuffle_tournament.id
  source                     text NOT NULL DEFAULT 'legacy'
);
CREATE UNIQUE INDEX standing_snapshots_competition_scope ON standing_snapshots (entry_id) WHERE group_member_id IS NULL;

CREATE TABLE matches_v2 (
  id                       bigserial PRIMARY KEY,   -- old league match ids are kept
  group_id                 bigint NOT NULL REFERENCES competition_groups(id) ON DELETE CASCADE,
  round_id                 integer NOT NULL REFERENCES rounds(id),
  scheduled_at             timestamp,
  court                    text,
  status                   text NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'played', 'cancelled', 'walkover')),
  home_pair_id             integer REFERENCES pairs(id),
  away_pair_id             integer REFERENCES pairs(id),
  bracket_code             text,
  winner_to_match_id       bigint REFERENCES matches_v2(id),
  loser_to_match_id        bigint REFERENCES matches_v2(id),
  legacy_shuffle_match_id  integer UNIQUE,
  legacy_ord               bigint,
  created_at               timestamp NOT NULL DEFAULT now(),
  updated_at               timestamp NOT NULL DEFAULT now(),
  updated_by_user_id       bigint
);

CREATE TABLE match_sets (
  match_id    bigint NOT NULL REFERENCES matches_v2(id) ON DELETE CASCADE,
  set_no      smallint NOT NULL CHECK (set_no BETWEEN 1 AND 5),
  home_games  integer,
  away_games  integer,
  outcome     text NOT NULL DEFAULT 'completed' CHECK (outcome IN ('completed', 'timeout_draw', 'not_started')),
  PRIMARY KEY (match_id, set_no)
);

-- One row per known occupant of a slot. A slot with no row is "unknown"
-- (shown as Substituto): history never recorded who filled in.
CREATE TABLE match_participants (
  id         bigserial PRIMARY KEY,               -- old players_in_match ids are kept
  match_id   bigint NOT NULL REFERENCES matches_v2(id) ON DELETE CASCADE,
  side       text NOT NULL CHECK (side IN ('home', 'away')),
  slot       smallint NOT NULL CHECK (slot IN (1, 2)),
  role       text NOT NULL CHECK (role IN ('member', 'substitute')),
  entry_id   integer REFERENCES entries(id),
  player_id  bigint NOT NULL REFERENCES players(id),
  legacy_ord bigint,
  UNIQUE (match_id, side, slot),
  UNIQUE (match_id, player_id),
  CHECK ((role = 'member') = (entry_id IS NOT NULL))
);

CREATE TABLE absences (
  id          serial PRIMARY KEY,
  entry_id    integer NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
  round_id    integer NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
  kind        text NOT NULL CHECK (kind IN ('full', 'partial')),
  source      text NOT NULL CHECK (source IN ('derived', 'recorded')),
  created_at  timestamp NOT NULL DEFAULT now(),
  created_by_user_id bigint,
  UNIQUE (entry_id, round_id)
);

CREATE TABLE award_events (
  id              serial PRIMARY KEY,
  competition_id  bigint NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
  stage_id        integer REFERENCES stages(id),
  group_id        bigint REFERENCES competition_groups(id),
  awarded_at      timestamp,
  source          text NOT NULL DEFAULT 'computed'
);
ALTER TABLE ranking_snapshots ADD FOREIGN KEY (after_award_event_id) REFERENCES award_events(id);

CREATE TABLE awards (
  id              serial PRIMARY KEY,
  award_event_id  integer NOT NULL REFERENCES award_events(id) ON DELETE CASCADE,
  entry_id        integer NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
  player_id       bigint NOT NULL REFERENCES players(id),
  group_id        bigint REFERENCES competition_groups(id),
  place           integer,
  rating          bigint,
  place_points    double precision NOT NULL DEFAULT 0,
  bonus_points    double precision NOT NULL DEFAULT 0,
  wins            integer NOT NULL DEFAULT 0,
  draws           integer NOT NULL DEFAULT 0,
  UNIQUE (award_event_id, entry_id)
);

CREATE TABLE ranking_entries (
  snapshot_id  integer NOT NULL REFERENCES ranking_snapshots(id) ON DELETE CASCADE,
  player_id    bigint NOT NULL REFERENCES players(id),
  points       double precision NOT NULL,
  position     integer,
  PRIMARY KEY (snapshot_id, player_id)
);

CREATE TABLE ranking_slot_values (
  snapshot_id     integer NOT NULL REFERENCES ranking_snapshots(id) ON DELETE CASCADE,
  player_id       bigint NOT NULL REFERENCES players(id),
  competition_id  bigint NOT NULL REFERENCES competitions(id),
  points          double precision NOT NULL,
  source          text NOT NULL DEFAULT 'scored' CHECK (source IN ('scored', 'zero', 'joker', 'seed')),
  PRIMARY KEY (snapshot_id, player_id, competition_id)
);

CREATE TABLE golden_tickets (
  id                     serial PRIMARY KEY,
  player_id              bigint NOT NULL REFERENCES players(id),
  level                  integer NOT NULL,
  source_competition_id  bigint REFERENCES competitions(id),
  earned_at              timestamp NOT NULL DEFAULT now(),
  status                 text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'used', 'void')),
  expires_at             timestamp
);

CREATE TABLE vacancies (
  id                  serial PRIMARY KEY,
  competition_id      bigint NOT NULL REFERENCES competitions(id),
  tier                integer NOT NULL,
  opened_by_entry_id  integer REFERENCES entries(id),
  opened_at           timestamp NOT NULL DEFAULT now(),
  filled_by           text CHECK (filled_by IN ('golden_ticket', 'promotion', 'substitution')),
  golden_ticket_id    integer REFERENCES golden_tickets(id),
  filled_entry_id     integer REFERENCES entries(id)
);

CREATE TABLE audit_events (
  id             bigserial PRIMARY KEY,
  actor_user_id  bigint,
  entity         text NOT NULL,
  entity_id      bigint,
  action         text NOT NULL,
  before         jsonb,
  after          jsonb,
  at             timestamp NOT NULL DEFAULT now()
);

------------------------------------------------------------------------------
-- 3. Copy data
------------------------------------------------------------------------------

-- Ranking rules: the one the code uses today, and the settled 2026/27 rule.
INSERT INTO ranking_rules (key, name, mode, last_n) VALUES
  ('legacy-last-4-by-id', 'Last 4 editions by id (rule until 2026)', 'last_n_by_id', 4),
  ('transitional-2026-27', 'Last 3 completed + current (2026/27)', 'last_n_completed_plus_current', 3),
  ('per-slot', 'Each event replaces its counterpart (from 2027/28)', 'per_slot', NULL);

-- Seasons: September to July, from each edition's first match. The empty
-- duplicate edition 14 takes the season of the edition before it.
CREATE TEMP TABLE edition_dates AS
SELECT e.id AS edition_id, e.league_id,
       min(m.date_hour) AS first_match,
       max(m.date_hour) AS last_match
FROM legacy.editions e
LEFT JOIN legacy.divisions d ON d.edition_id = e.id
LEFT JOIN legacy.matches m ON m.division_id = d.id OR (m.division_id IS NULL AND d.id = 3 AND m.id IN (85, 86))
GROUP BY e.id, e.league_id;

UPDATE edition_dates ed SET first_match = prev.last_match
FROM (SELECT edition_id, lag(last_match) OVER (ORDER BY edition_id) AS last_match FROM edition_dates) prev
WHERE ed.edition_id = prev.edition_id AND ed.first_match IS NULL;

CREATE TEMP TABLE edition_season AS
SELECT edition_id, league_id,
       CASE WHEN extract(month FROM first_match) >= 9
            THEN extract(year FROM first_match)::int
            ELSE extract(year FROM first_match)::int - 1 END AS start_year
FROM edition_dates;

INSERT INTO seasons (league_id, name, starts_on, ends_on)
SELECT DISTINCT league_id, start_year || '/' || lpad(((start_year + 1) % 100)::text, 2, '0'),
       make_date(start_year, 9, 1), make_date(start_year + 1, 7, 31)
FROM edition_season
UNION
SELECT 1, '2025/26', DATE '2025-09-01', DATE '2026-07-31'   -- the shuffle season
ORDER BY 2;

-- 2026/27 is settled: 1 Sep 2026 to 27 Jul 2027, transitional ranking rule.
UPDATE seasons SET starts_on = DATE '2026-09-01', ends_on = DATE '2027-07-27',
       ranking_rule_id = (SELECT id FROM ranking_rules WHERE key = 'transitional-2026-27')
WHERE name = '2026/27';
UPDATE seasons SET ranking_rule_id = (SELECT id FROM ranking_rules WHERE key = 'legacy-last-4-by-id')
WHERE ranking_rule_id IS NULL;

INSERT INTO event_slots (league_id, key, name, format, holds_ranking_slot, calendar_order) VALUES
  (1, 'classica-1', 'Clássica I',   'classica',  true, 1),
  (1, 'teams',      'Teams',        'teams',     true, 2),
  (1, 'classica-2', 'Clássica II',  'classica',  true, 3),
  (1, 'shuffle',    'Shuffle',      'shuffle',   true, 4),
  (1, 'classica-3', 'Clássica III', 'classica',  true, 5),
  (1, 'super-cup',  'Super Cup',    'super_cup', NULL, 6);

-- Editions -> classica competitions (ids kept).
INSERT INTO competitions (id, season_id, name, format, status, starts_on, ends_on, legacy_ord)
SELECT e.id,
       s.id,
       e.name,
       'classica',
       CASE WHEN EXISTS (SELECT 1 FROM legacy.divisions d WHERE d.edition_id = e.id)
             AND NOT EXISTS (SELECT 1 FROM legacy.divisions d WHERE d.edition_id = e.id AND d.has_ended IS NOT TRUE)
            THEN 'ended' ELSE 'planned' END,
       ed.first_match::date,
       ed.last_match::date,
       row_number() OVER (ORDER BY e.ctid)
FROM legacy.editions e
JOIN edition_season es ON es.edition_id = e.id
JOIN edition_dates ed ON ed.edition_id = e.id
JOIN seasons s ON s.league_id = es.league_id
             AND s.name = es.start_year || '/' || lpad(((es.start_year + 1) % 100)::text, 2, '0');

-- Edition 25 (22ª) is Clássica I of 2026/27.
UPDATE competitions SET event_slot_id = (SELECT id FROM event_slots WHERE key = 'classica-1') WHERE id = 25;

-- The shuffle becomes a competition after every edition id.
INSERT INTO competitions (id, season_id, name, format, status, rules, legacy_shuffle_id, title)
SELECT (SELECT max(id) FROM legacy.editions) + st.id,
       (SELECT id FROM seasons WHERE name = '2025/26'),
       st.title,
       'shuffle',
       CASE WHEN st.has_ended THEN 'ended' ELSE 'running' END,
       jsonb_build_object(
         'current_matchweek', st.current_matchweek,
         'max_players', st.max_players,
         'number_of_divisions', st.number_of_divisions,
         'has_ended', st.has_ended,
         'division_multipliers', st.division_multipliers_raw::jsonb
       ),
       st.id,
       st.title
FROM legacy.shuffle_tournaments st;

SELECT setval(pg_get_serial_sequence('competitions', 'id'), (SELECT max(id) FROM competitions));

-- Classica: one stage per competition, rounds 1..7.
INSERT INTO stages (competition_id, number, name, seeding_method, emits_award, status)
SELECT c.id, 1, NULL, 'promotion', true, c.status
FROM competitions c WHERE c.format = 'classica';

INSERT INTO rounds (stage_id, number, date)
SELECT st.id, mw.matchweek, NULL
FROM stages st
JOIN competitions c ON c.id = st.competition_id AND c.format = 'classica'
CROSS JOIN LATERAL (
  SELECT DISTINCT m.matchweek
  FROM legacy.divisions d
  JOIN legacy.matches m ON m.division_id = d.id
  WHERE d.edition_id = c.id
) mw;

-- Divisions -> groups (ids kept). Tier from the rating ladder.
INSERT INTO competition_groups (id, stage_id, tier, name, rating, starts_at, end_date, has_ended,
                                open_division, standings_up_to_date, logo_image_id, large_picture_id, legacy_ord)
SELECT d.id, st.id,
       CASE d.rating WHEN 2000 THEN 1 WHEN 1000 THEN 2 WHEN 500 THEN 3
                     WHEN 250 THEN 4 WHEN 125 THEN 5 WHEN 63 THEN 6 END,
       d.name, d.rating, d.beginning_datetime, d.end_date, d.has_ended,
       d.open_division, d.standings_up_to_date, d.logo_image_id, d.large_picture_id,
       row_number() OVER (ORDER BY d.ctid)
FROM legacy.divisions d
JOIN stages st ON st.competition_id = d.edition_id AND st.number = 1;

SELECT setval(pg_get_serial_sequence('competition_groups', 'id'), (SELECT max(id) FROM competition_groups));

-- Entries and group members (players_in_division ids kept).
INSERT INTO entries (competition_id, player_id, final_place, legacy_ord)
SELECT d.edition_id, pid.player_id, pid.place, row_number() OVER (ORDER BY pid.ctid)
FROM legacy.players_in_division pid
JOIN legacy.divisions d ON d.id = pid.division_id;

INSERT INTO group_members (id, group_id, entry_id, legacy_ord)
SELECT pid.id, pid.division_id, en.id, row_number() OVER (ORDER BY pid.ctid)
FROM legacy.players_in_division pid
JOIN legacy.divisions d ON d.id = pid.division_id
JOIN entries en ON en.competition_id = d.edition_id AND en.player_id = pid.player_id;

SELECT setval(pg_get_serial_sequence('group_members', 'id'), (SELECT max(id) FROM group_members));

INSERT INTO standing_snapshots (entry_id, group_member_id, place, points, appearances, percentage_of_appearances,
                                wins, draws, losses, games_won, games_lost, matchweek)
SELECT gm.entry_id, gm.id, pid.place, pid.points, pid.appearances, pid.percentage_of_appearances,
       pid.wins, pid.draws, pid.losts, pid.games_won, pid.games_lost, pid.matchweek
FROM legacy.players_in_division pid
JOIN group_members gm ON gm.id = pid.id;

-- Places follow the computed order (points, presences, games difference;
-- remaining ties keep the stored order). Pedro, 2026-10-14: the computed
-- order wins over manual overrides. In the 2026-10-14 data this only changes
-- division 69 (intended difference D7).
WITH ranked AS (
  SELECT ss.id,
         row_number() OVER (PARTITION BY gm.group_id
                            ORDER BY ss.points DESC NULLS LAST, ss.appearances DESC NULLS LAST,
                                     (coalesce(ss.games_won, 0) - coalesce(ss.games_lost, 0)) DESC,
                                     gm.legacy_ord) AS computed_place
  FROM standing_snapshots ss
  JOIN group_members gm ON gm.id = ss.group_member_id
)
UPDATE standing_snapshots ss SET place = r.computed_place
FROM ranked r WHERE r.id = ss.id AND ss.place IS DISTINCT FROM r.computed_place;

UPDATE entries en SET final_place = ss.place
FROM standing_snapshots ss
WHERE ss.entry_id = en.id AND ss.group_member_id IS NOT NULL AND en.final_place IS DISTINCT FROM ss.place;

-- League matches (ids kept). Matches 85 and 86 lost their division_id; they
-- are division 3, jornada 1 (intended difference D1).
INSERT INTO matches_v2 (id, group_id, round_id, scheduled_at, court, status, legacy_ord)
SELECT m.id,
       coalesce(m.division_id, 3),
       r.id,
       m.date_hour,
       m.field,
       CASE WHEN m.played THEN 'played' ELSE 'scheduled' END,
       row_number() OVER (ORDER BY m.ctid)
FROM legacy.matches m
JOIN competition_groups g ON g.id = coalesce(m.division_id, 3)
JOIN rounds r ON r.stage_id = g.stage_id AND r.number = m.matchweek;

INSERT INTO match_sets (match_id, set_no, home_games, away_games, outcome)
SELECT m.id, 1, m.games_home_team, m.games_away_team, 'completed'
FROM legacy.matches m
WHERE m.games_home_team IS NOT NULL OR m.games_away_team IS NOT NULL;

INSERT INTO match_participants (id, match_id, side, slot, role, entry_id, player_id, legacy_ord)
SELECT pim.id, pim.match_id, lower(pim.team),
       row_number() OVER (PARTITION BY pim.match_id, pim.team ORDER BY pim.ctid),
       CASE WHEN en.id IS NULL THEN 'substitute' ELSE 'member' END,
       en.id, pim.player_id, row_number() OVER (ORDER BY pim.ctid)
FROM legacy.players_in_match pim
JOIN matches_v2 mv ON mv.id = pim.match_id
JOIN competition_groups g ON g.id = mv.group_id
JOIN stages st ON st.id = g.stage_id
LEFT JOIN entries en ON en.competition_id = st.competition_id AND en.player_id = pim.player_id;

SELECT setval(pg_get_serial_sequence('matches_v2', 'id'), (SELECT max(id) FROM matches_v2));

-- Shuffle: entries, one stage + round per matchweek, one group per division.
INSERT INTO entries (competition_id, player_id, final_place, legacy_ord)
SELECT c.id, pst.player_id, pst.position, row_number() OVER (ORDER BY pst.ctid)
FROM legacy.players_in_shuffle_tournament pst
JOIN competitions c ON c.legacy_shuffle_id = pst.shuffle_tournament_id;

INSERT INTO standing_snapshots (entry_id, place, points, wins, draws, losses, games_played,
                                games_won, games_lost, next_division, legacy_id)
SELECT en.id, pst.position, pst.points, pst.wins, pst.draws, pst.losses, pst.games_played,
       pst.games_won, pst.games_lost, pst.division_number, pst.id
FROM legacy.players_in_shuffle_tournament pst
JOIN competitions c ON c.legacy_shuffle_id = pst.shuffle_tournament_id
JOIN entries en ON en.competition_id = c.id AND en.player_id = pst.player_id;

INSERT INTO stages (competition_id, number, name, seeding_method, emits_award, status)
SELECT c.id, sm.matchweek, NULL, 'standings', false,
       'ended'
FROM competitions c
JOIN (SELECT DISTINCT shuffle_tournament_id, matchweek FROM legacy.shuffle_matches) sm
  ON sm.shuffle_tournament_id = c.legacy_shuffle_id;

INSERT INTO rounds (stage_id, number)
SELECT st.id, st.number FROM stages st JOIN competitions c ON c.id = st.competition_id AND c.format = 'shuffle';

INSERT INTO competition_groups (stage_id, tier, name, rating, multiplier, has_ended)
SELECT st.id, dv.division, NULL, NULL,
       (c.rules -> 'division_multipliers' ->> dv.division::text)::int,
       NULL
FROM stages st
JOIN competitions c ON c.id = st.competition_id AND c.format = 'shuffle'
JOIN (SELECT DISTINCT shuffle_tournament_id, matchweek, division FROM legacy.shuffle_matches) dv
  ON dv.shuffle_tournament_id = c.legacy_shuffle_id AND dv.matchweek = st.number;

INSERT INTO matches_v2 (group_id, round_id, status, legacy_shuffle_match_id, legacy_ord)
SELECT g.id, r.id, CASE WHEN sm.played THEN 'played' ELSE 'scheduled' END, sm.id,
       row_number() OVER (ORDER BY sm.ctid)
FROM legacy.shuffle_matches sm
JOIN competitions c ON c.legacy_shuffle_id = sm.shuffle_tournament_id
JOIN stages st ON st.competition_id = c.id AND st.number = sm.matchweek
JOIN competition_groups g ON g.stage_id = st.id AND g.tier = sm.division
JOIN rounds r ON r.stage_id = st.id
ORDER BY sm.id;

INSERT INTO match_sets (match_id, set_no, home_games, away_games, outcome)
SELECT mv.id, 1, sm.score1, sm.score2, 'completed'
FROM legacy.shuffle_matches sm
JOIN matches_v2 mv ON mv.legacy_shuffle_match_id = sm.id
WHERE sm.score1 IS NOT NULL OR sm.score2 IS NOT NULL;

SELECT setval(pg_get_serial_sequence('match_participants', 'id'), (SELECT max(id) FROM match_participants));

INSERT INTO match_participants (match_id, side, slot, role, entry_id, player_id, legacy_ord)
SELECT mv.id, lower(psm.team::text),
       row_number() OVER (PARTITION BY psm.shuffle_match_id, psm.team ORDER BY psm.ctid),
       CASE WHEN en.id IS NULL THEN 'substitute' ELSE 'member' END,
       en.id, psm.player_id, row_number() OVER (ORDER BY psm.ctid)
FROM legacy.players_in_shuffle_match psm
JOIN matches_v2 mv ON mv.legacy_shuffle_match_id = psm.shuffle_match_id
JOIN competition_groups g ON g.id = mv.group_id
JOIN stages st ON st.id = g.stage_id
LEFT JOIN entries en ON en.competition_id = st.competition_id AND en.player_id = psm.player_id
ORDER BY psm.id;

-- Shuffle group membership per round, rebuilt from who played where.
INSERT INTO group_members (group_id, entry_id)
SELECT DISTINCT mv.group_id, mp.entry_id
FROM match_participants mp
JOIN matches_v2 mv ON mv.id = mp.match_id
WHERE mv.legacy_shuffle_match_id IS NOT NULL AND mp.entry_id IS NOT NULL;

-- Derived absences: a member with fewer than 3 games in a round.
INSERT INTO absences (entry_id, round_id, kind, source)
SELECT gm.entry_id, r.id,
       CASE WHEN coalesce(played.n, 0) = 0 THEN 'full' ELSE 'partial' END,
       'derived'
FROM group_members gm
JOIN competition_groups g ON g.id = gm.group_id
JOIN stages st ON st.id = g.stage_id
JOIN competitions c ON c.id = st.competition_id AND c.format = 'classica'
JOIN rounds r ON r.stage_id = st.id
LEFT JOIN LATERAL (
  SELECT count(*) AS n
  FROM match_participants mp JOIN matches_v2 mv ON mv.id = mp.match_id
  WHERE mp.entry_id = gm.entry_id AND mv.round_id = r.id AND mv.status = 'played'
) played ON true
WHERE coalesce(played.n, 0) < 3
  AND EXISTS (SELECT 1 FROM matches_v2 mv WHERE mv.group_id = g.id AND mv.round_id = r.id AND mv.status = 'played');

INSERT INTO absences (entry_id, round_id, kind, source)
SELECT en.id, r.id,
       CASE WHEN coalesce(played.n, 0) = 0 THEN 'full' ELSE 'partial' END,
       'derived'
FROM entries en
JOIN competitions c ON c.id = en.competition_id AND c.format = 'shuffle'
JOIN stages st ON st.competition_id = c.id
JOIN rounds r ON r.stage_id = st.id
LEFT JOIN LATERAL (
  SELECT count(*) AS n
  FROM match_participants mp JOIN matches_v2 mv ON mv.id = mp.match_id
  WHERE mp.entry_id = en.id AND mv.round_id = r.id AND mv.status = 'played'
) played ON true
WHERE coalesce(played.n, 0) < 3;

-- Awards: one event per ended classica group, using the stored place and
-- wins/draws counted from the matches (as compute_ranking_points does).
INSERT INTO award_events (competition_id, stage_id, group_id, awarded_at, source)
SELECT st.competition_id, st.id, g.id, g.end_date, 'backfill'
FROM competition_groups g
JOIN stages st ON st.id = g.stage_id
JOIN competitions c ON c.id = st.competition_id AND c.format = 'classica'
WHERE g.has_ended IS TRUE AND g.open_division IS NOT TRUE;

INSERT INTO awards (award_event_id, entry_id, player_id, group_id, place, rating,
                    place_points, bonus_points, wins, draws)
SELECT ae.id, gm.entry_id, en.player_id, g.id, ss.place, g.rating,
       floor(g.rating * power(0.75::double precision, ss.place - 1)),
       res.wins * (g.rating / 100.0::double precision) + res.draws * (g.rating / 250.0::double precision),
       res.wins, res.draws
FROM award_events ae
JOIN competition_groups g ON g.id = ae.group_id
JOIN group_members gm ON gm.group_id = g.id
JOIN entries en ON en.id = gm.entry_id
JOIN standing_snapshots ss ON ss.group_member_id = gm.id
CROSS JOIN LATERAL (
  SELECT count(*) FILTER (WHERE (mp.side = 'home' AND s.home_games > s.away_games)
                             OR (mp.side = 'away' AND s.away_games > s.home_games)) AS wins,
         count(*) FILTER (WHERE s.home_games = s.away_games) AS draws
  FROM match_participants mp
  JOIN matches_v2 mv ON mv.id = mp.match_id AND mv.group_id = g.id AND mv.status = 'played'
  JOIN match_sets s ON s.match_id = mv.id AND s.set_no = 1
  WHERE mp.player_id = en.player_id
) res;

-- The ranking as stored today becomes the first snapshot.
INSERT INTO ranking_snapshots (league_id, rule_id, computed_at, note)
SELECT 1, id, now(), 'Imported from players.ranking_points / ranking_position at migration'
FROM ranking_rules WHERE key = 'legacy-last-4-by-id';

INSERT INTO ranking_entries (snapshot_id, player_id, points, position)
SELECT (SELECT max(id) FROM ranking_snapshots), p.id, coalesce(p.ranking_points, 0), p.ranking_position
FROM players p;

------------------------------------------------------------------------------
-- 4. Drop the old competition tables from public (copies are in legacy)
------------------------------------------------------------------------------
DROP TABLE players_in_shuffle_match, players_in_shuffle_tournament, shuffle_matches, shuffle_tournaments,
           players_in_match, players_in_division, matches, divisions;
-- registrations reference editions; editions become a compat view.
DROP TABLE editions;
ALTER TABLE matches_v2 RENAME TO matches;

------------------------------------------------------------------------------
-- 5. Real keys on the tables that keep their shape
------------------------------------------------------------------------------
ALTER TABLE users ALTER COLUMN id SET NOT NULL;
ALTER TABLE users ADD PRIMARY KEY (id);
ALTER TABLE users ADD CONSTRAINT users_player_id_key UNIQUE (player_id);
ALTER TABLE users ADD CONSTRAINT users_player_id_fkey FOREIGN KEY (player_id) REFERENCES players(id);

ALTER TABLE players ADD COLUMN status text NOT NULL DEFAULT 'member'
  CHECK (status IN ('member', 'external', 'former', 'expelled'));

ALTER TABLE news ALTER COLUMN id SET NOT NULL;
ALTER TABLE news ADD PRIMARY KEY (id);
ALTER TABLE orders ALTER COLUMN id SET NOT NULL;
ALTER TABLE orders ADD PRIMARY KEY (id);
ALTER TABLE orders ADD FOREIGN KEY (user_id) REFERENCES users(id);
ALTER TABLE products ALTER COLUMN id SET NOT NULL;
ALTER TABLE products ADD PRIMARY KEY (id);
ALTER TABLE order_lines ALTER COLUMN id SET NOT NULL;
ALTER TABLE order_lines ADD PRIMARY KEY (id);
ALTER TABLE order_lines ADD FOREIGN KEY (order_id) REFERENCES orders(id);
ALTER TABLE order_lines ADD FOREIGN KEY (product_id) REFERENCES products(id);
ALTER TABLE product_images ALTER COLUMN id SET NOT NULL;
ALTER TABLE product_images ADD PRIMARY KEY (id);
ALTER TABLE product_images ADD FOREIGN KEY (product_id) REFERENCES products(id);
ALTER TABLE product_attributes ALTER COLUMN id SET NOT NULL;
ALTER TABLE product_attributes ADD PRIMARY KEY (id);
ALTER TABLE product_attribute_values ALTER COLUMN id SET NOT NULL;
ALTER TABLE product_attribute_values ADD PRIMARY KEY (id);
ALTER TABLE product_attributes_in_product ALTER COLUMN id SET NOT NULL;
ALTER TABLE product_attributes_in_product ADD PRIMARY KEY (id);
ALTER TABLE product_attribute_values_in_product ALTER COLUMN id SET NOT NULL;
ALTER TABLE product_attribute_values_in_product ADD PRIMARY KEY (id);
ALTER TABLE registrations ADD PRIMARY KEY (player_id, edition_id);
ALTER TABLE registrations ADD FOREIGN KEY (player_id) REFERENCES players(id);
ALTER TABLE registrations ADD FOREIGN KEY (edition_id) REFERENCES competitions(id);
