#!/bin/bash

TIMESTAMP=$(date +"%Y-%m-%d_%H-%M")
BACKUP_NAME="padel_league_$TIMESTAMP.sql.gz"
BACKUP_PATH="/tmp/$BACKUP_NAME"
BUCKET="gs://portopadelleague-storage/db_backups"

# Credentials: PGPASSWORD from the environment or from ~/.backup.env on the VM
# (a file with `PGPASSWORD=...`, mode 600). The literal below is the legacy value
# and only applies when neither is set; delete it once the password is rotated.
if [ -f "$HOME/.backup.env" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.backup.env"
fi
export PGPASSWORD="${PGPASSWORD:-portopadelleague}"

# Dump and compress
pg_dump -U padel_user -h localhost -d padel_league | gzip > "$BACKUP_PATH"

# Upload to GCS
gsutil cp "$BACKUP_PATH" "$BUCKET/"

# Clean up
rm "$BACKUP_PATH"
