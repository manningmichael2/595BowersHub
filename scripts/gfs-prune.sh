#!/bin/bash
# GFS (grandfather-father-son) retention selector — PURE, no side effects.
#
# Reads candidate backup directory names on stdin (one per line), each named
# like "YYYY-MM-DD_HHMM" (the format scripts/backup.sh uses), and prints one
# line per input:  "KEEP <name>"  or  "DELETE <name>".
#
# It keeps the UNION of three tiers (same semantics as restic/borg
# --keep-daily/--keep-weekly/--keep-monthly):
#   - the newest $DAILY directories
#   - the newest directory in each of the newest $WEEKLY ISO-weeks
#   - the newest directory in each of the newest $MONTHLY calendar months
# Everything else is marked DELETE.
#
# Defaults: 7 daily, 4 weekly, 6 monthly (local backup.sh keeps 7 days on disk;
# this is the longer-lived off-site policy).
#
# Safety: a name whose date can't be parsed is ALWAYS kept — we never delete
# something we don't understand. The caller (backup.sh) decides what to do with
# the DELETE lines; this script touches nothing.
set -euo pipefail

DAILY=${DAILY:-7}
WEEKLY=${WEEKLY:-4}
MONTHLY=${MONTHLY:-6}

# Read non-blank names, newest first.
mapfile -t NAMES < <(grep -v '^[[:space:]]*$' || true)
if (( ${#NAMES[@]} == 0 )); then
  exit 0
fi
IFS=$'\n' NAMES=($(printf '%s\n' "${NAMES[@]}" | sort -r)); unset IFS

declare -A KEEP WEEK_SEEN MONTH_SEEN
daily_kept=0
weeks_kept=0
months_kept=0

for name in "${NAMES[@]}"; do
  datepart=${name%%_*}                       # YYYY-MM-DD
  if ! date -d "$datepart" +%s >/dev/null 2>&1; then
    KEEP[$name]=1                            # unparseable -> never delete
    continue
  fi
  week=$(date -d "$datepart" +%G-%V)         # ISO year-week
  month=$(date -d "$datepart" +%Y-%m)        # calendar month

  if (( daily_kept < DAILY )); then
    KEEP[$name]=1
    daily_kept=$((daily_kept + 1))
  fi
  if [[ -z ${WEEK_SEEN[$week]:-} ]]; then
    WEEK_SEEN[$week]=1
    if (( weeks_kept < WEEKLY )); then
      KEEP[$name]=1
      weeks_kept=$((weeks_kept + 1))
    fi
  fi
  if [[ -z ${MONTH_SEEN[$month]:-} ]]; then
    MONTH_SEEN[$month]=1
    if (( months_kept < MONTHLY )); then
      KEEP[$name]=1
      months_kept=$((months_kept + 1))
    fi
  fi
done

for name in "${NAMES[@]}"; do
  if [[ -n ${KEEP[$name]:-} ]]; then
    echo "KEEP $name"
  else
    echo "DELETE $name"
  fi
done
