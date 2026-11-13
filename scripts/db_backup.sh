#!/bin/bash
set -euo pipefail

TIMESTAMP=$(date +"%Y-%m-%d_%H-%M")
# Own suffix, so this dump never shares a name with (or is overwritten by) the
# legacy ~/scripts/backup.sh, which uploads padel_league_<date>_03-00.sql.gz
BACKUP_NAME="padel_league_${TIMESTAMP}_db_backup.sql.gz"
BACKUP_PATH="/tmp/$BACKUP_NAME"
BUCKET="gs://portopadelleague-storage/db_backups"

# Credentials: PGPASSWORD from ~/.backup.env (mode 600), written by the deploy
# from the POSTGRES_PW secret.
if [ -f "$HOME/.backup.env" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.backup.env"
fi
: "${PGPASSWORD:?PGPASSWORD not set: ~/.backup.env missing}"
export PGPASSWORD

# Dump and compress (pipefail: a failed pg_dump fails the backup instead of
# uploading an empty file)
pg_dump -U padel_user -h localhost -d padel_league | gzip > "$BACKUP_PATH"

# Upload to GCS
gsutil cp "$BACKUP_PATH" "$BUCKET/"

# Clean up
rm "$BACKUP_PATH"
