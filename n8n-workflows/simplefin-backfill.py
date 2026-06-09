#!/usr/bin/env python3
"""One-shot backfill: pull last 14 days of SimpleFin transactions and upsert into Postgres.

Run from the server side. Mirrors what the SimpleFin Nightly Sync workflow does.
"""
import json
import urllib.request
import urllib.error
import os
import sys
from datetime import datetime, timedelta

# Auth from environment variable (never hardcode credentials)
SIMPLEFIN_AUTH = os.environ.get("SIMPLEFIN_AUTH")
if not SIMPLEFIN_AUTH:
    print("ERROR: Set SIMPLEFIN_AUTH env var (e.g. 'Basic <base64>')", file=sys.stderr)
    sys.exit(1)

# Get Postgres password from environment or prompt
DB_PASS = os.environ.get("DB_PASSWORD")
if not DB_PASS:
    print("ERROR: Set DB_PASSWORD env var", file=sys.stderr)
    sys.exit(1)

# Ignored account IDs (from the workflow)
IGNORED_ACCOUNT_IDS = {"ACT-ad8f670e-99f0-4259-b5e1-73721805d770",
                        "ACT-c04ed2cb-9b38-4d38-a685-d98fc22434d0"}

# Fetch from SimpleFin with 14-day window
start = datetime.now() - timedelta(days=14)
start_ts = int(start.replace(hour=0, minute=0, second=0).timestamp())
url = f"https://beta-bridge.simplefin.org/simplefin/accounts?start-date={start_ts}"

req = urllib.request.Request(url, headers={"Authorization": SIMPLEFIN_AUTH})
print(f"Fetching from SimpleFin (start: {start.strftime('%Y-%m-%d')})...")
with urllib.request.urlopen(req, timeout=60) as resp:
    data = json.load(resp)

print(f"Got {len(data.get('accounts', []))} accounts and {len(data.get('errors', []))} errors\n")

if data.get('errors'):
    print("Connection errors (these accounts won't sync until re-auth at SimpleFin Bridge):")
    for e in data['errors']:
        print(f"  ⚠️  {e}")
    print()

# Collect transactions
transactions = []
for account in data.get('accounts', []):
    if account['id'] in IGNORED_ACCOUNT_IDS:
        continue
    for txn in account.get('transactions', []):
        posted_date = None
        if txn.get('posted'):
            posted_date = datetime.fromtimestamp(txn['posted']).strftime('%Y-%m-%d')
        transactions.append({
            'id': txn['id'],
            'account_id': account['id'],
            'posted_date': posted_date,
            'amount': float(txn.get('amount') or 0),
            'description': txn.get('description', ''),
            'memo': txn.get('memo', ''),
            'pending': bool(txn.get('pending', False)),
        })

print(f"Total transactions across all accounts: {len(transactions)}\n")
if not transactions:
    print("No transactions to insert.")
    sys.exit(0)

# Group by date for visibility
from collections import Counter
date_counts = Counter(t['posted_date'] for t in transactions)
print("By date:")
for d in sorted(date_counts.keys(), reverse=True):
    print(f"  {d}: {date_counts[d]} txns")

# Insert via psql exec into postgres container
import subprocess
print("\nInserting into Postgres (ON CONFLICT DO NOTHING)...")

inserted = 0
skipped = 0
for t in transactions:
    desc_safe = t['description'].replace("'", "''")
    memo_safe = t['memo'].replace("'", "''")
    txn_id_safe = t['id'].replace("'", "''")
    
    sql = f"""
INSERT INTO public.transactions (id, account_id, posted_date, amount, description, memo, pending, source)
VALUES ('{txn_id_safe}', '{t['account_id']}', '{t['posted_date']}', {t['amount']}, '{desc_safe}', '{memo_safe}', {str(t['pending']).lower()}, 'simplefin')
ON CONFLICT (id) DO NOTHING
RETURNING id;
"""
    
    result = subprocess.run(
        ["docker", "exec", "-i", "postgres", "psql", "-U", "michael", "-d", "finance", "-tAc", sql],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  ERROR on {t['id']}: {result.stderr.strip()[:200]}")
        continue
    output = result.stdout.strip()
    if output:
        inserted += 1
    else:
        skipped += 1

print(f"\n✓ Inserted: {inserted} new transactions")
print(f"  Skipped (already exist): {skipped}")
