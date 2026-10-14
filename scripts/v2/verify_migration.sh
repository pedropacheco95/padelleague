#!/bin/bash
# Verify the v2 migration lost nothing: every row of every old competition
# table must be reproduced exactly by its compat view.
#
#   scripts/v2/verify_migration.sh <database> [psql connection flags]
#
# Prints legacy-only / compat-only row counts per table; both must be 0,
# except matches (85 and 86 now carry division 3, D1) and players_in_division
# (division 69 places follow the computed order, D7: 3 rows).
set -euo pipefail
DB="$1"; shift || true
CONN=("$@")
q() { psql -d "$DB" "${CONN[@]}" -At -c "$SQL"; }

check() {
  local table="$1" cols="$2"
  SQL="select count(*) from (select $cols from legacy.$table except select $cols from compat.$table) x"; a=$(q)
  SQL="select count(*) from (select $cols from compat.$table except select $cols from legacy.$table) x"; b=$(q)
  SQL="select count(*) from legacy.$table"; n=$(q)
  printf '%-32s rows=%-6s legacy-only=%-4s compat-only=%s\n' "$table" "$n" "$a" "$b"
}

check editions "id, name, league_id"
check divisions "id, name, beginning_datetime, rating, end_date, has_ended, open_division, edition_id, logo_image_id, large_picture_id, standings_up_to_date"
check matches "id, games_home_team, games_away_team, date_hour, winner, matchweek, field, played, division_id"
check players_in_match "id, player_id, match_id, team"
check players_in_division "id, player_id, division_id, place, points, appearances, percentage_of_appearances, wins, draws, losts, games_won, games_lost, matchweek"
check shuffle_tournaments "id, title, current_matchweek, max_players, number_of_divisions, has_ended, division_multipliers_raw::jsonb::text"
check shuffle_matches "id, shuffle_tournament_id, matchweek, division, score1, score2, played"
check players_in_shuffle_tournament "id, player_id, shuffle_tournament_id, division_number, points, wins, draws, losses, games_played, games_won, games_lost, position"
check players_in_shuffle_match "player_id, shuffle_match_id, team::text"

# Tables kept in place must still match their archived copy row for row.
for t in players users news sponsors sponsor_clicks chatbot_logs backend_app images orders order_lines products product_images registrations leagues; do
  cols=$(psql -d "$DB" "${CONN[@]}" -At -c "select string_agg(quote_ident(column_name), ',') from information_schema.columns where table_schema='legacy' and table_name='$t'")
  SQL="select count(*) from (select $cols from legacy.$t except select $cols from public.$t) x"; a=$(q)
  SQL="select count(*) from legacy.$t"; n=$(q)
  printf '%-32s rows=%-6s changed-or-missing=%s\n' "public.$t" "$n" "$a"
done
