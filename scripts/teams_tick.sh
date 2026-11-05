#!/bin/bash
# Hourly: the Teams steps that happen on their own (see services/teams_schedule.py).
sudo docker exec ppl python -m flask --app app v2 teams-tick 2>&1 | while read -r line; do
  echo "$(date -u +%FT%TZ) $line"
done >> "$HOME/teams_tick.log"
