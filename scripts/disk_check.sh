#!/bin/bash
# Daily: email the admin when the root disk is over 80% (issue #74).
LIMIT=80
USED=$(df --output=pcent / | tail -1 | tr -dc '0-9')
echo "$(date -u +%FT%TZ) root disk ${USED}%" >> "$HOME/disk_check.log"
if [ "$USED" -ge "$LIMIT" ]; then
  SUMMARY=$(df -h / | tail -1; sudo docker system df 2>/dev/null)
  sudo docker exec ppl python -m flask --app app v2 alert "VM disk at ${USED}%" "$SUMMARY" >> "$HOME/disk_check.log" 2>&1
fi
