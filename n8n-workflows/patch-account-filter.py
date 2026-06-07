#!/usr/bin/env python3
"""
Patch the deployed SimpleFin Nightly Sync and Historical Load workflows so
they skip known-bogus account IDs from SimpleFin.

Why this exists
---------------
SimpleFin/HealthEquity returns multiple "accounts" for what is really a single
HealthEquity HSA bucket -- e.g., two distinct ACT- IDs both named "Investments"
with identical balances, and a separate "Balances" bucket. These are not real
bank accounts and should not be tracked. Without this filter, every nightly
sync re-creates them in Postgres along with duplicated transactions.

How
---
- Replaces the "Transform Accounts for Postgres" node's jsCode with a version
  that skips IDs in IGNORED_ACCOUNT_IDS.
- Replaces the "Transform Transactions for Postgres" node's jsCode with a
  version that skips transactions whose parent account_id is in the same set.
- Idempotent: re-running detects the already-patched marker and is a no-op.

Add new IDs by editing IGNORED_ACCOUNT_IDS below and re-running the script.
"""

import json
import sys
import urllib.request

from _config import API_KEY, N8N_URL
BASE = f"{N8N_URL}/api/v1"
HEADERS = {"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"}

# Workflows to patch (id, transactions-source-node-name)
TARGETS = [
    ("XF9ye6jAAO012Ys4", "SimpleFin-StartDate"),  # SimpleFin Nightly Sync
    ("1BcxrSvq0MXRQut6", "HTTP Request"),         # Historical Load (Postgres)
]

# Accounts that SimpleFin returns but we never want in our DB.
# Each entry: {"id": "ACT-...", "reason": "..."} -- reason is for posterity.
IGNORED_ACCOUNT_IDS = [
    {
        "id": "ACT-ad8f670e-99f0-4259-b5e1-73721805d770",
        "reason": "HealthEquity duplicate Investments bucket (SimpleFin returns two with identical balance)",
    },
    {
        "id": "ACT-c04ed2cb-9b38-4d38-a685-d98fc22434d0",
        "reason": "HealthEquity Balances bucket -- not a real account, transactions overlap with Investments",
    },
]

PATCH_MARKER = "// PATCH:account-filter-v1"

# JS injected at the top of both transform nodes.
IGNORE_LIST_JS_TEMPLATE = """{marker}
// Maintained by patch-account-filter.py. To add another bogus account
// from SimpleFin, edit IGNORED_ACCOUNT_IDS in that script and re-run.
const IGNORED_ACCOUNT_IDS = new Set({ids});
"""


def build_account_transform(ids_json: str) -> str:
    return (
        IGNORE_LIST_JS_TEMPLATE.format(marker=PATCH_MARKER, ids=ids_json)
        + """
const items = $input.all();
const results = [];

for (const item of items) {
  const accounts = item.json.accounts || [];
  for (const account of accounts) {
    if (IGNORED_ACCOUNT_IDS.has(account.id)) continue;

    let balanceDate = null;
    if (account["balance-date"]) {
      const d = new Date(account["balance-date"] * 1000);
      balanceDate = d.toISOString().split("T")[0];
    }
    const orgName = (account.org ? account.org.name : '').replace(/'/g, "''");
    const acctName = (account.name || '').replace(/'/g, "''");
    const acctId = (account.id || '').replace(/'/g, "''");

    results.push({
      json: {
        id: acctId,
        org_name: orgName,
        account_name: acctName,
        currency: account.currency || 'USD',
        last_balance: parseFloat(account.balance) || 0,
        last_balance_date: balanceDate
      }
    });
  }
}
return results;
"""
    )


def build_transaction_transform(ids_json: str, source_node: str) -> str:
    return (
        IGNORE_LIST_JS_TEMPLATE.format(marker=PATCH_MARKER, ids=ids_json)
        + f"""
const simplefinItems = $("{source_node}").all();
const results = [];

for (const item of simplefinItems) {{
  const accounts = item.json.accounts || [];
  for (const account of accounts) {{
    if (IGNORED_ACCOUNT_IDS.has(account.id)) continue;

    const accountId = account.id;
    const transactions = account.transactions || [];
    for (const txn of transactions) {{
      let postedDate = null;
      if (txn.posted) {{
        const d = new Date(txn.posted * 1000);
        postedDate = d.toISOString().split("T")[0];
      }}
      const desc = (txn.description || '').replace(/'/g, "''");
      const memo = (txn.memo || '').replace(/'/g, "''");
      const acctId = accountId.replace(/'/g, "''");
      const txnId = txn.id.replace(/'/g, "''");

      results.push({{
        json: {{
          id: txnId,
          account_id: acctId,
          posted_date: postedDate,
          amount: parseFloat(txn.amount) || 0,
          description: desc,
          memo: memo,
          pending: txn.pending === true ? true : false
        }}
      }});
    }}
  }}
}}
return results;
"""
    )


def api(method: str, path: str, data=None):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(BASE + path, data=body, headers=HEADERS, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def patch_workflow(workflow_id: str, tx_source_node: str, dry_run: bool):
    wf = api("GET", f"/workflows/{workflow_id}")
    name = wf.get("name")
    print(f"\n[{workflow_id}] {name}")

    ids_json = json.dumps([entry["id"] for entry in IGNORED_ACCOUNT_IDS])
    new_account_js = build_account_transform(ids_json)
    new_tx_js = build_transaction_transform(ids_json, tx_source_node)

    changed = False
    for node in wf.get("nodes", []):
        nname = node.get("name", "")
        if nname == "Transform Accounts for Postgres":
            current = node["parameters"].get("jsCode", "")
            if current.strip() == new_account_js.strip():
                print("  - 'Transform Accounts' already current, skipping")
            else:
                node["parameters"]["jsCode"] = new_account_js
                changed = True
                print("  - 'Transform Accounts' updated")
        elif nname == "Transform Transactions for Postgres":
            current = node["parameters"].get("jsCode", "")
            if current.strip() == new_tx_js.strip():
                print("  - 'Transform Transactions' already current, skipping")
            else:
                node["parameters"]["jsCode"] = new_tx_js
                changed = True
                print("  - 'Transform Transactions' updated")

    if not changed:
        print("  -> no changes needed")
        return

    if dry_run:
        print("  -> DRY RUN, not pushing")
        return

    # n8n's PUT /workflows/:id rejects unknown properties on settings.
    # Whitelist the few keys it does accept.
    allowed_settings_keys = {
        "executionOrder",
        "saveDataErrorExecution",
        "saveDataSuccessExecution",
        "saveExecutionProgress",
        "saveManualExecutions",
        "callerPolicy",
        "errorWorkflow",
        "timezone",
        "executionTimeout",
    }
    raw_settings = wf.get("settings") or {}
    settings = {k: v for k, v in raw_settings.items() if k in allowed_settings_keys}
    payload = {
        "name": wf["name"],
        "nodes": wf["nodes"],
        "connections": wf["connections"],
        "settings": settings,
    }
    api("PUT", f"/workflows/{workflow_id}", payload)
    print("  -> pushed")


def main():
    dry_run = "--dry-run" in sys.argv
    print(f"Patching with {len(IGNORED_ACCOUNT_IDS)} ignored account ID(s):")
    for entry in IGNORED_ACCOUNT_IDS:
        print(f"  - {entry['id']}  ({entry['reason']})")
    for wid, tx_src in TARGETS:
        try:
            patch_workflow(wid, tx_src, dry_run)
        except urllib.error.HTTPError as e:
            print(f"  -> HTTPError: {e.code} {e.reason}", file=sys.stderr)
            print(e.read().decode(errors="replace"), file=sys.stderr)
            raise


if __name__ == "__main__":
    main()
