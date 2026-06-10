#!/usr/bin/env python3
"""Dump full SimpleFin response from the most recent execution."""
import json
import urllib.request
import os

API_KEY = os.environ["N8N_API_KEY"]
BASE = "http://localhost:5678/api/v1"
SIMPLEFIN_ID = "XF9ye6jAAO012Ys4"


def get(path):
    req = urllib.request.Request(f"{BASE}{path}", headers={"X-N8N-API-KEY": API_KEY})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


execs = get(f"/executions?workflowId={SIMPLEFIN_ID}&limit=1&includeData=true").get("data", [])
ex = execs[0]
run_data = ex.get("data", {}).get("resultData", {}).get("runData", {})

for node_name, runs in run_data.items():
    if 'simplefin' in node_name.lower() or 'http' in node_name.lower():
        run = runs[0]
        output = run.get("data", {}).get("main", [[]])
        if output and len(output) > 0 and output[0]:
            item = output[0][0].get("json", {})
            
            # Show errors
            errors = item.get("errors", [])
            print(f"\n=== Errors ({len(errors)}) ===")
            for e in errors:
                print(f"  {e}")
            
            # Show accounts and their transactions
            accounts = item.get("accounts", [])
            print(f"\n=== Accounts ({len(accounts)}) ===")
            total_txns = 0
            for acc in accounts:
                name = acc.get("name", "?")
                org = acc.get("org", {}).get("name", "?")
                bal = acc.get("balance", "?")
                bal_date_ts = acc.get("balance-date")
                bal_date = ""
                if bal_date_ts:
                    from datetime import datetime
                    bal_date = datetime.fromtimestamp(bal_date_ts).strftime("%Y-%m-%d")
                
                txns = acc.get("transactions", [])
                total_txns += len(txns)
                
                if txns:
                    print(f"  ★ {org} / {name} — bal {bal} ({bal_date}) — {len(txns)} txns")
                    for t in txns[:3]:
                        tdate = ""
                        if t.get("posted"):
                            tdate = datetime.fromtimestamp(t["posted"]).strftime("%Y-%m-%d")
                        print(f"      {tdate} ${t.get('amount')} — {t.get('description', '')[:50]}")
                else:
                    print(f"    {org} / {name} — bal {bal} ({bal_date}) — 0 txns")
            
            print(f"\nTotal transactions across all accounts: {total_txns}")
        break  # Only need one
