#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

TIME_OF_DAY="${1:-21:00}"
LABEL="${2:-backup}"
LOG_FILE="${WRITING_BACKUP_LOG:-$REPO_ROOT/.git/daily-writing-backup.log}"

if [[ ! "$TIME_OF_DAY" =~ ^([01]?[0-9]|2[0-3]):[0-5][0-9]$ ]]; then
  echo "Usage: $0 [HH:MM] [label]" >&2
  echo "Example: $0 21:30 backup" >&2
  exit 1
fi

hour="${TIME_OF_DAY%%:*}"
minute="${TIME_OF_DAY##*:}"
hour="$((10#$hour))"
minute="$((10#$minute))"

marker_start="# BEGIN rowze daily writing backup"
marker_end="# END rowze daily writing backup"
cron_command="WRITING_BACKUP_LABEL=\"$LABEL\" \"$REPO_ROOT/website/static/scripts/daily_writing_backup.sh\" >> \"$LOG_FILE\" 2>&1"
cron_line="$minute $hour * * * $cron_command"

existing="$(crontab -l 2>/dev/null || true)"
cleaned="$(printf '%s\n' "$existing" | sed "/$marker_start/,/$marker_end/d")"

{
  printf '%s\n' "$cleaned" | sed '/^[[:space:]]*$/d'
  printf '%s\n' "$marker_start"
  printf '%s\n' "$cron_line"
  printf '%s\n' "$marker_end"
} | crontab -

chmod +x "$REPO_ROOT/website/static/scripts/daily_writing_backup.sh"

echo "Installed daily writing backup cron job:"
echo "$cron_line"
echo "Log file: $LOG_FILE"
