#!/bin/bash
# Tests for gfs-prune.sh — pure selection logic, no rclone/network.
# Run: bash scripts/test_gfs_prune.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRUNE="$HERE/gfs-prune.sh"
fail=0

# Helper: feed names (newline-sep), return the KEPT names sorted.
kept() { printf '%s\n' "$1" | DAILY="${2:-7}" WEEKLY="${3:-4}" MONTHLY="${4:-6}" \
  bash "$PRUNE" | sed -n 's/^KEEP //p' | sort; }
deleted() { printf '%s\n' "$1" | DAILY="${2:-7}" WEEKLY="${3:-4}" MONTHLY="${4:-6}" \
  bash "$PRUNE" | sed -n 's/^DELETE //p' | sort; }

assert_eq() { # $1=desc $2=got $3=want
  if [[ "$2" == "$3" ]]; then echo "ok - $1"; else
    echo "FAIL - $1"; echo "  got:  $(echo "$2" | tr '\n' ' ')"; echo "  want: $(echo "$3" | tr '\n' ' ')"; fail=1
  fi
}

# 1. Fewer than DAILY -> keep everything.
names=$'2026-06-19_0300\n2026-06-18_0300\n2026-06-17_0300'
assert_eq "keeps all when below daily limit" \
  "$(deleted "$names")" ""

# 2. 30 consecutive daily backups, default 7d/4w/6m.
#    Daily window keeps the 7 newest. Beyond that, weekly keeps newest-per-week
#    (4 weeks) and monthly newest-per-month (6 months). Older dailies get deleted.
names=""; for i in $(seq 0 29); do
  d=$(date -d "2026-06-19 -$i day" +%Y-%m-%d); names+="${d}_0300"$'\n'
done
names=${names%$'\n'}
k=$(kept "$names")
kcount=$(echo "$k" | grep -c . )
# Must keep the 7 newest dailies explicitly.
for i in 0 1 2 3 4 5 6; do
  d=$(date -d "2026-06-19 -$i day" +%Y-%m-%d)_0300
  echo "$k" | grep -qx "$d" || { echo "FAIL - daily $d missing from keep"; fail=1; }
done
# Over 30 days we span ~5 ISO weeks and 2 months; union should keep well under 30
# but more than 7 (weeklies/monthlies beyond the daily window add a few).
if (( kcount >= 7 && kcount < 30 )); then echo "ok - 30-day set pruned to $kcount (7<=k<30)";
else echo "FAIL - 30-day kept $kcount (expected 7..29)"; fail=1; fi

# 3. Two backups same day -> daily tier keeps newest of the day within its count,
#    but BOTH count against nothing weird; the older same-day one is deletable
#    once outside all windows. Here with only 2 entries, both fit daily -> kept.
names=$'2026-06-19_0300\n2026-06-19_0900'
assert_eq "two same-day both kept when under limits" "$(deleted "$names")" ""

# 4. Unparseable names are never deleted.
names=$'not-a-date\n2026-06-19_0300\nrandom_folder'
del=$(deleted "$names")
assert_eq "unparseable names never deleted" "$del" ""

# 5. Deterministic monthly: one backup per month for 12 months, 0 daily/0 weekly,
#    6 monthly -> keep newest 6 months only.
names=""; for i in $(seq 0 11); do
  d=$(date -d "2026-06-15 -$i month" +%Y-%m-%d); names+="${d}_0300"$'\n'
done
names=${names%$'\n'}
k=$(kept "$names" 0 0 6)
kcount=$(echo "$k" | grep -c .)
assert_eq "12 monthly, keep-monthly=6 -> 6 kept" "$kcount" "6"
# Newest 6 months present, 7th-oldest absent.
for i in 0 1 2 3 4 5; do
  d=$(date -d "2026-06-15 -$i month" +%Y-%m-%d)_0300
  echo "$k" | grep -qx "$d" || { echo "FAIL - month $d missing"; fail=1; }
done
d7=$(date -d "2026-06-15 -6 month" +%Y-%m-%d)_0300
echo "$k" | grep -qx "$d7" && { echo "FAIL - month $d7 should be pruned"; fail=1; }

# 6. Empty input -> no output, exit 0.
out=$(printf '' | bash "$PRUNE"); assert_eq "empty input -> empty output" "$out" ""

if (( fail )); then echo "SOME TESTS FAILED"; exit 1; else echo "ALL TESTS PASSED"; fi
