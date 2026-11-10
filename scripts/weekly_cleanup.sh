#!/bin/bash
# Weekly: drop unused Docker images and cap the journal (issue #74).
{
  echo "$(date -u +%FT%TZ) cleanup"
  sudo docker image prune -f
  sudo journalctl --vacuum-size=200M
  df -h /
} >> "$HOME/weekly_cleanup.log" 2>&1
