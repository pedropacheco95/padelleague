#!/bin/bash

TIMESTAMP=$(date +"%Y-%m-%d_%H-%M")
BACKUP_NAME="padel_league_$TIMESTAMP.sql.gz"
BACKUP_PATH="/tmp/$BACKUP_NAME"
BUCKET="gs://portopadelleague-storage/db_backups"

# Dump and compress
PGPASSWORD="portopadelleague" pg_dump -U padel_user -h localhost -d padel_league | gzip > "$BACKUP_PATH"

# Upload to GCS
gsutil cp "$BACKUP_PATH" "$BUCKET/"

# Clean up
rm "$BACKUP_PATH"
