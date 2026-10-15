#!/bin/bash
# Timed rehearsal of the production cut-over, on localhost only.
#
#   TEST_DB_PREFIX=s6 scripts/parity/rehearse_cutover.sh <backup.sql.gz> [label]
#
# Steps (mirrors docs/v2/qa/cutover.md):
#   1 restore   backup → ${P}_reh (stands in for the production database)
#   2 snapshot  row counts + alembic_version ("pre")
#   3 backup    pg_dump | gzip, as scripts/backup.sh does in production
#   4 upgrade   flask db upgrade (this checkout's migrations, to head)
#   5 verify    verify_migration.sh, read by rule R3 (docs/v2/qa/gates.md)
#   6 smoke     this checkout's app on :$PORT against the migrated db, smoke URLs must be 200
#   7 rollback  drop, restore the step-3 dump, compare with "pre"
# Writes a timing table to stdout and to $OUT/rehearsal_<label>.md. Exit 0 only if all green.
set -uo pipefail
cd "$(dirname "$0")/../.."
SRC="$1"; LABEL="${2:-$(date +%H%M)}"
: "${TEST_DB_PREFIX:?set TEST_DB_PREFIX}"
P="$TEST_DB_PREFIX"; DB="${P}_reh"; PORT="${PORT:-5064}"
# Production restores, migrates and serves as padel_user (not a superuser), owner
# of its database. The rehearsal does the same; ROLE=postgres to compare.
ROLE="${ROLE:-padel_user}"; AS=(-h localhost -U "$ROLE")
OUT="${OUT:-${TMPDIR:-/tmp}/${P}_rehearsal}"; mkdir -p "$OUT"
PG=(-h localhost -U postgres)
DUMP="$OUT/pre_cutover_$LABEL.sql.gz"
REPORT="$OUT/rehearsal_$LABEL.md"
ok=1; rows=()

step() {  # step <name> <command...>; times it, records pass/fail
  local name="$1"; shift
  local t0=$(date +%s)
  if "$@" >"$OUT/$name.log" 2>&1; then r=ok; else r=FAIL; ok=0; fi
  rows+=("| $name | $r | $(( $(date +%s) - t0 ))s |")
  echo "$name: $r ($(( $(date +%s) - t0 ))s)"
  [[ $r == ok ]]
}

snapshot() {  # snapshot <db> → "table count" lines for every public table + alembic_version
  psql "${PG[@]}" -d "$1" -Atc "select version_num from alembic_version"
  for t in $(psql "${PG[@]}" -d "$1" -Atc "select tablename from pg_tables where schemaname='public' order by 1"); do
    echo "$t $(psql "${PG[@]}" -d "$1" -Atc "select count(*) from public.\"$t\"")"
  done
}

restore() {  # restore <gz> <db>
  psql "${PG[@]}" -d postgres -Atqc "select pg_terminate_backend(pid) from pg_stat_activity where datname='$2'" >/dev/null
  dropdb "${PG[@]}" --if-exists "$2" && createdb "${PG[@]}" -O "$ROLE" "$2" \
    && gunzip -c "$1" | psql -q -v ON_ERROR_STOP=1 "${AS[@]}" -d "$2" >/dev/null
}

upgrade() {
  POSTGRES_HOST=localhost POSTGRES_USER="$ROLE" POSTGRES_PW= POSTGRES_DB="$DB" FLASK_APP=padel_league \
    .venv/bin/flask db upgrade
}

verify() {  # rule R3
  # D7 may read 0/0 only if division 69 already holds the computed order (6, 3, 4).
  local d7; d7=$(psql "${PG[@]}" -d "$DB" -Atc "select string_agg(place::text, ',' order by player_id) from legacy.players_in_division where division_id=69 and player_id in (38,52,86)")
  echo "legacy division 69 places (38,52,86): $d7"
  scripts/v2/verify_migration.sh "$DB" "${PG[@]}" | tee "$OUT/verify_$LABEL.txt" | awk '
    /legacy-only=/ { split($3,a,"="); split($4,b,"=");
      if ($1=="matches") { if (!(a[2]==2 && b[2]==2)) { print "R3 matches expects 2/2 (D1): " $0; bad=1 } }
      else if ($1=="players_in_division") { if (!((a[2]==3 && b[2]==3) || (a[2]==0 && b[2]==0 && d7=="6,3,4"))) { print "R3 D7: " $0; bad=1 } }
      else if (a[2]!=0 || b[2]!=0) { print "R3: " $0; bad=1 } }
    /changed-or-missing=/ { split($3,c,"="); if (c[2]!=0) { print "R3: " $0; bad=1 } }
    END { exit bad }' d7="$d7"
}

smoke() {
  POSTGRES_HOST=localhost POSTGRES_USER="$ROLE" POSTGRES_PW= POSTGRES_DB="$DB" FLASK_ENV=development \
    LLM_API_KEY= MAIL_PASSWORD= GCS_UPLOADS_BUCKET=parity-bucket \
    .venv/bin/flask --app padel_league run --port "$PORT" >"$OUT/flask_$LABEL.log" 2>&1 &
  local pid=$!
  trap "kill $pid 2>/dev/null" RETURN
  for _ in $(seq 60); do curl -s -o /dev/null "http://127.0.0.1:$PORT/api/v1/players/ranking" && break; sleep 0.5; done
  local bad=0
  while read -r path; do
    [[ -z "$path" || "$path" == \#* ]] && continue
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT$path")
    echo "$code $path"; [[ "$code" == 200 ]] || bad=1
  done < scripts/parity/smoke_urls.txt
  return $bad
}

rollback() {
  restore "$DUMP" "$DB" && snapshot "$DB" > "$OUT/post_rollback_$LABEL.txt" \
    && diff "$OUT/pre_$LABEL.txt" "$OUT/post_rollback_$LABEL.txt"
}

T0=$(date +%s)
snap_pre() { snapshot "$DB" > "$OUT/pre_$LABEL.txt"; }
do_backup() { pg_dump "${PG[@]}" -d "$DB" | gzip > "$DUMP"; }

step restore restore "$SRC" "$DB" \
  && step snapshot snap_pre \
  && step backup do_backup \
  && { M0=$(date +%s); step upgrade upgrade && step verify verify; MW=$(( $(date +%s) - M0 )); } \
  && step smoke smoke
step rollback rollback   # always attempted, even after a failure: rollback must work from any state
TOTAL=$(( $(date +%s) - T0 ))

{
  echo "# Cut-over rehearsal $LABEL ($(date '+%Y-%m-%d %H:%M'))"
  echo
  echo "Source: \`$SRC\` · role: $ROLE · server: $(psql "${PG[@]}" -Atc 'show server_version') · code: \`$(git rev-parse --short HEAD)\` · head: $(git -c core.pager=cat log -1 --format=%s | cut -c1-60)"
  echo
  echo "| step | result | time |"; echo "|---|---|---|"; printf '%s\n' "${rows[@]}"
  echo
  echo "Migration window (upgrade + verify): ${MW:-n/a}s · total: ${TOTAL}s · verdict: $([[ $ok == 1 ]] && echo GREEN || echo RED)"
} | tee "$REPORT"
[[ $ok == 1 ]]
