-- Schema `compat`: the old table shapes as read-only views over the v2 tables.
-- The pre-v2 ORM classes map onto these, so the existing serializers keep
-- producing identical JSON while code moves to the v2 models. Drop this schema
-- once nothing maps onto it.

CREATE SCHEMA compat;

CREATE VIEW compat.editions AS
SELECT c.id, c.name, s.league_id
FROM competitions c
JOIN seasons s ON s.id = c.season_id
WHERE c.format = 'classica'
ORDER BY coalesce(c.legacy_ord, 1000000000000 + c.id);

CREATE VIEW compat.divisions AS
SELECT g.id, g.name, g.starts_at AS beginning_datetime, g.rating, g.end_date,
       g.has_ended, g.open_division, st.competition_id AS edition_id,
       g.logo_image_id, g.large_picture_id, g.standings_up_to_date
FROM competition_groups g
JOIN stages st ON st.id = g.stage_id
JOIN competitions c ON c.id = st.competition_id AND c.format = 'classica'
ORDER BY coalesce(g.legacy_ord, 1000000000000 + g.id);

CREATE VIEW compat.matches AS
SELECT m.id,
       s.home_games AS games_home_team,
       s.away_games AS games_away_team,
       m.scheduled_at AS date_hour,
       CASE WHEN s.home_games IS NULL OR s.away_games IS NULL THEN NULL
            ELSE sign(s.home_games - s.away_games)::bigint END AS winner,
       r.number::bigint AS matchweek,
       m.court AS field,
       (m.status = 'played') AS played,
       m.group_id AS division_id
FROM matches m
JOIN rounds r ON r.id = m.round_id
JOIN compat.divisions d ON d.id = m.group_id
LEFT JOIN match_sets s ON s.match_id = m.id AND s.set_no = 1
ORDER BY coalesce(m.legacy_ord, 1000000000000 + m.id);

CREATE VIEW compat.players_in_match AS
SELECT mp.id, mp.player_id, mp.match_id,
       CASE mp.side WHEN 'home' THEN 'Home' ELSE 'Away' END AS team
FROM match_participants mp
JOIN compat.matches m ON m.id = mp.match_id
ORDER BY coalesce(mp.legacy_ord, 1000000000000 + mp.id);

-- Standings: the frozen row when the group has one, otherwise computed from
-- the matches the same way Division.update_table did.
CREATE VIEW compat.players_in_division AS
WITH live AS (
  SELECT gm.id, gm.group_id, gm.entry_id,
         count(mp.id) AS appearances,
         count(mp.id) FILTER (WHERE (mp.side = 'home' AND s.home_games > s.away_games)
                               OR (mp.side = 'away' AND s.away_games > s.home_games)) AS wins,
         count(mp.id) FILTER (WHERE s.home_games = s.away_games) AS draws,
         count(mp.id) FILTER (WHERE (mp.side = 'home' AND s.home_games < s.away_games)
                               OR (mp.side = 'away' AND s.away_games < s.home_games)) AS losts,
         coalesce(sum(CASE mp.side WHEN 'home' THEN s.home_games WHEN 'away' THEN s.away_games END), 0) AS games_won,
         coalesce(sum(CASE mp.side WHEN 'home' THEN s.away_games WHEN 'away' THEN s.home_games END), 0) AS games_lost
  FROM group_members gm
  JOIN compat.divisions d ON d.id = gm.group_id
  LEFT JOIN matches m ON m.group_id = gm.group_id AND m.status = 'played'
  LEFT JOIN match_participants mp ON mp.match_id = m.id AND mp.entry_id = gm.entry_id
  LEFT JOIN match_sets s ON s.match_id = m.id AND s.set_no = 1
  WHERE NOT EXISTS (SELECT 1 FROM standing_snapshots ss WHERE ss.group_member_id = gm.id)
  GROUP BY gm.id, gm.group_id, gm.entry_id
),
live_mw AS (
  SELECT m.group_id, coalesce(max(r.number), 0) AS matchweek
  FROM matches m JOIN rounds r ON r.id = m.round_id
  WHERE m.status = 'played'
  GROUP BY m.group_id
),
live_rows AS (
  SELECT l.id, en.player_id, l.group_id AS division_id,
         row_number() OVER (PARTITION BY l.group_id
                            ORDER BY (3 * l.wins + l.draws) DESC, l.appearances DESC,
                                     (l.games_won - l.games_lost) DESC, l.id)::bigint AS place,
         (3 * l.wins + l.draws)::double precision AS points,
         l.appearances::bigint,
         round(((l.appearances::double precision / (coalesce(mw.matchweek, 0) + 1) * 3) * 100)::numeric, 2)::double precision
           AS percentage_of_appearances,
         l.wins::bigint, l.draws::bigint, l.losts::bigint,
         l.games_won::bigint, l.games_lost::bigint,
         coalesce(mw.matchweek, 0)::bigint AS matchweek,
         1000000000000 + l.id AS sort_key
  FROM live l
  JOIN entries en ON en.id = l.entry_id
  LEFT JOIN live_mw mw ON mw.group_id = l.group_id
)
SELECT gm.id, en.player_id, gm.group_id AS division_id,
       ss.place::bigint, ss.points, ss.appearances, ss.percentage_of_appearances,
       ss.wins, ss.draws, ss.losses AS losts, ss.games_won, ss.games_lost, ss.matchweek,
       coalesce(gm.legacy_ord, 1000000000000 + gm.id) AS sort_key
FROM standing_snapshots ss
JOIN group_members gm ON gm.id = ss.group_member_id
JOIN entries en ON en.id = gm.entry_id
JOIN compat.divisions d ON d.id = gm.group_id
UNION ALL
SELECT id, player_id, division_id, place, points, appearances, percentage_of_appearances,
       wins, draws, losts, games_won, games_lost, matchweek, sort_key
FROM live_rows
ORDER BY sort_key;

CREATE VIEW compat.shuffle_tournaments AS
SELECT coalesce(c.legacy_shuffle_id, c.id)::integer AS id,
       coalesce(c.title, c.name) AS title,
       coalesce((c.rules ->> 'current_matchweek')::int, 1) AS current_matchweek,
       coalesce((c.rules ->> 'max_players')::int, 48) AS max_players,
       coalesce((c.rules ->> 'number_of_divisions')::int, 6) AS number_of_divisions,
       (c.rules ->> 'has_ended')::boolean AS has_ended,
       coalesce((c.rules -> 'division_multipliers')::text, '{}') AS division_multipliers_raw,
       c.id AS competition_id
FROM competitions c
WHERE c.format = 'shuffle';

CREATE VIEW compat.shuffle_matches AS
SELECT coalesce(m.legacy_shuffle_match_id, m.id)::integer AS id,
       t.id AS shuffle_tournament_id,
       st.number AS matchweek,
       g.tier AS division,
       s.home_games AS score1,
       s.away_games AS score2,
       (m.status = 'played') AS played,
       m.id AS match_id
FROM matches m
JOIN competition_groups g ON g.id = m.group_id
JOIN stages st ON st.id = g.stage_id
JOIN compat.shuffle_tournaments t ON t.competition_id = st.competition_id
LEFT JOIN match_sets s ON s.match_id = m.id AND s.set_no = 1
ORDER BY coalesce(m.legacy_ord, 1000000000000 + m.id);

-- Stats are computed from the matches (as recalculate_player_stats does);
-- division_number and position keep their stored values.
CREATE VIEW compat.players_in_shuffle_tournament AS
WITH played AS (
  SELECT mp.entry_id, g.multiplier,
         CASE mp.side WHEN 'home' THEN s.home_games ELSE s.away_games END AS own,
         CASE mp.side WHEN 'home' THEN s.away_games ELSE s.home_games END AS opp
  FROM match_participants mp
  JOIN matches m ON m.id = mp.match_id AND m.status = 'played'
  JOIN match_sets s ON s.match_id = m.id AND s.set_no = 1
  JOIN competition_groups g ON g.id = m.group_id
  WHERE mp.entry_id IS NOT NULL AND s.home_games IS NOT NULL AND s.away_games IS NOT NULL
),
totals AS (
  SELECT entry_id,
         sum(CASE WHEN own > opp THEN 3 * coalesce(multiplier, 1)
                  WHEN own = opp THEN coalesce(multiplier, 1) ELSE 0 END) AS points,
         count(*) FILTER (WHERE own > opp) AS wins,
         count(*) FILTER (WHERE own = opp) AS draws,
         count(*) FILTER (WHERE own < opp) AS losses,
         count(*) AS games_played,
         sum(own) AS games_won,
         sum(opp) AS games_lost
  FROM played GROUP BY entry_id
)
SELECT coalesce(ss.legacy_id, en.id)::integer AS id,
       en.player_id::integer,
       t.id AS shuffle_tournament_id,
       coalesce(ss.next_division, 1) AS division_number,
       coalesce(tt.points, 0)::integer AS points,
       coalesce(tt.wins, 0)::integer AS wins,
       coalesce(tt.draws, 0)::integer AS draws,
       coalesce(tt.losses, 0)::integer AS losses,
       coalesce(tt.games_played, 0)::integer AS games_played,
       coalesce(tt.games_won, 0)::integer AS games_won,
       coalesce(tt.games_lost, 0)::integer AS games_lost,
       ss.place AS position,
       en.id AS entry_id
FROM entries en
JOIN compat.shuffle_tournaments t ON t.competition_id = en.competition_id
LEFT JOIN standing_snapshots ss ON ss.entry_id = en.id AND ss.group_member_id IS NULL
LEFT JOIN totals tt ON tt.entry_id = en.id
ORDER BY coalesce(en.legacy_ord, 1000000000000 + en.id);

CREATE VIEW compat.players_in_shuffle_match AS
SELECT mp.id::integer, mp.player_id::integer, sm.id AS shuffle_match_id,
       CASE mp.side WHEN 'home' THEN 'Home' ELSE 'Away' END AS team
FROM match_participants mp
JOIN compat.shuffle_matches sm ON sm.match_id = mp.match_id
ORDER BY coalesce(mp.legacy_ord, 1000000000000 + mp.id);
