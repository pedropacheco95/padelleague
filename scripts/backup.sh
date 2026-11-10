#!/bin/bash
set -euo pipefail

TIMESTAMP=$(date +"%Y-%m-%d_%H-%M")
BACKUP_NAME="padel_league_$TIMESTAMP.sql.gz"
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
