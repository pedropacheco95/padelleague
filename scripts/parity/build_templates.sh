#!/bin/bash
# Build the two parity templates under one prefix, from a backup or a database.
#
#   TEST_DB_PREFIX=s6 scripts/parity/build_templates.sh <backup.sql.gz | source-db> <golden-code-dir>
#
#   ${TEST_DB_PREFIX}_golden_tpl  source + migrations up to GOLDEN_REV, run by <golden-code-dir>
#                                 (the code production runs, e.g. the feature/teams-pairs checkout)
#   ${TEST_DB_PREFIX}_v2_tpl      source + every migration of this checkout, then verify_migration.sh
#
# localhost only; touches no database outside the prefix.
set -euo pipefail
cd "$(dirname "$0")/../.."
SRC="$1"; GOLDEN_CODE="$2"
: "${TEST_DB_PREFIX:?set TEST_DB_PREFIX}"
GOLDEN_REV="${GOLDEN_REV:-a1d5c0e7b3f2}"
PG=(-h localhost -U postgres)
PY="$PWD/.venv/bin"

load() {  # load <db>
  dropdb "${PG[@]}" --if-exists "$1"
  if [[ -f "$SRC" ]]; then
    createdb "${PG[@]}" "$1"
    gunzip -c "$SRC" | psql -q "${PG[@]}" -d "$1" >/dev/null 2>&1
  else
    createdb "${PG[@]}" -T "$SRC" "$1"
  fi
}
upgrade() {  # upgrade <code-dir> <db> <rev>
  (cd "$1" && POSTGRES_HOST=localhost POSTGRES_USER=postgres POSTGRES_PW= POSTGRES_DB="$2" FLASK_APP=padel_league \
    "$PY/flask" db upgrade "$3")
}

G="${TEST_DB_PREFIX}_golden_tpl"; C="${TEST_DB_PREFIX}_v2_tpl"
t0=$SECONDS
load "$G"; upgrade "$GOLDEN_CODE" "$G" "$GOLDEN_REV"
echo "$G ready ($(psql "${PG[@]}" -d "$G" -Atc 'select version_num from alembic_version'), $((SECONDS-t0))s)"
t0=$SECONDS
load "$C"; upgrade "$PWD" "$C" head
echo "$C ready ($(psql "${PG[@]}" -d "$C" -Atc 'select version_num from alembic_version'), $((SECONDS-t0))s)"
scripts/v2/verify_migration.sh "$C" "${PG[@]}"
