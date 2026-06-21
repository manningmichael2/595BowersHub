"""Populate finance.accounts.account_type (R6.2 prerequisite) so the
TransferDetector's liability-payment path works — a payment INTO a credit_card/
loan/mortgage account is a confirmed transfer even when only one leg is imported.
Then re-run the historical transfer backfill to catch single-leg CC/loan payment
stragglers. Idempotent; valid types: checking|savings|credit_card|loan|mortgage|brokerage.
Ambiguous/0-txn accounts are deliberately left NULL."""
import asyncio

from backend.config import load_config
from backend.database import close_pool, get_pool, init_pool
from backend.services.categorization.transfer_backfill import backfill_transfer_flags

# (account_name ILIKE pattern, account_type). Order doesn't matter — patterns are disjoint.
MAPPING = [
    ("%Amazon Prime Rewards Visa%", "credit_card"),
    ("%Platinum Card%", "credit_card"),
    ("%Costco Anywhere Visa%", "credit_card"),
    ("%Personal Loan%", "loan"),
    ("Spend (0161)%", "checking"),
    ("Savings Account%", "savings"),
    ("Reserve (0188)%", "savings"),
    ("Investments", "brokerage"),
    ("Growth (0196)%", "brokerage"),
    ("HSA FOR LIFE%", "brokerage"),
]


async def main():
    await init_pool(load_config())
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            for pat, typ in MAPPING:
                res = await conn.execute(
                    "UPDATE finance.accounts SET account_type=$1 WHERE account_name ILIKE $2",
                    typ, pat)
                print(f"{typ:11s} <- {pat!r:36s} {res}", flush=True)

            print("\n-- account_type now --", flush=True)
            rows = await conn.fetch(
                "SELECT account_name, COALESCE(account_type,'(null)') t FROM finance.accounts ORDER BY t, account_name")
            for r in rows:
                print(f"   {r['t']:12s} {r['account_name']}", flush=True)

            before = await conn.fetchval(
                "SELECT count(*) FROM finance.transactions WHERE is_transfer=true")
        print(f"\nis_transfer before backfill: {before}", flush=True)

        # Now liability-payment detection is live → re-run the historical backfill.
        print("re-running backfill_transfer_flags ...", flush=True)
        print("   ", await backfill_transfer_flags(), flush=True)

        async with pool.acquire() as conn:
            after = await conn.fetchval(
                "SELECT count(*) FROM finance.transactions WHERE is_transfer=true")
            print(f"is_transfer after backfill:  {after}", flush=True)
            print("\n-- remaining uncategorized payment-like rows (should shrink) --", flush=True)
            rows = await conn.fetch(
                "SELECT t.amount, t.is_transfer, left(t.description,45) d FROM finance.transactions t "
                "WHERE t.category_id IS NULL AND t.user_category_override=false AND t.is_transfer=false "
                "  AND t.is_investment=false "
                "  AND (t.description ILIKE '%payment%' OR t.description ILIKE '%autopay%' "
                "       OR t.description ILIKE '%epay%' OR t.description ILIKE '%pmt%') "
                "ORDER BY t.posted_date DESC")
            if not rows:
                print("   NONE", flush=True)
            for r in rows:
                print(f"   {float(r['amount']):>10.2f} transfer={r['is_transfer']}  {r['d']}", flush=True)
    finally:
        await close_pool()


asyncio.run(main())
