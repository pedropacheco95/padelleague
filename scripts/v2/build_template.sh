#!/bin/bash
# Build the local v2 test template from a production backup.
#
#   scripts/v2/build_template.sh [backup.sql.gz | source-db]   (default: padel_league_prod_20261015)
#
# Result: database `v2_template` = backup → every migration up to head →
# verify_migration.sh. Never point this at production; it only uses localhost.
# Sessions clone it:  createdb -h localhost -U postgres -T v2_template ${TEST_DB_PREFIX}_dev
set -euo pipefail
cd "$(dirname "$0")/../.."
SRC="${1:-padel_league_prod_20261015}"
PG=(-h localhost -U postgres)
BUILD=v2_template_build

dropdb "${PG[@]}" --if-exists "$BUILD"
if [[ -f "$SRC" ]]; then
  createdb "${PG[@]}" "$BUILD"
  gunzip -c "$SRC" | psql -q "${PG[@]}" -d "$BUILD" >/dev/null 2>&1
else
  createdb "${PG[@]}" -T "$SRC" "$BUILD"
fi

POSTGRES_HOST=localhost POSTGRES_USER=postgres POSTGRES_PW= POSTGRES_DB="$BUILD" FLASK_APP=padel_league \
  .venv/bin/flask db upgrade

bad=$(scripts/v2/verify_migration.sh "$BUILD" "${PG[@]}" | awk '/legacy-only=/ && ($3!="legacy-only=0" || $4!="compat-only=0") && $1!="matches"; /changed-or-missing=/ && $3!="changed-or-missing=0"')
if [[ -n "$bad" ]]; then echo "verification failed:"; echo "$bad"; exit 1; fi

# Connections to the template block cloning; terminate stragglers first.
psql "${PG[@]}" -d postgres -Atqc "select pg_terminate_backend(pid) from pg_stat_activity where datname='v2_template'" >/dev/null
dropdb "${PG[@]}" --if-exists v2_template
psql "${PG[@]}" -d postgres -qc "ALTER DATABASE $BUILD RENAME TO v2_template"
echo "v2_template ready (head: $(psql "${PG[@]}" -d v2_template -Atc 'select version_num from alembic_version'))"
