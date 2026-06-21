"""Dry-run candidate normalization rules against ALL real transaction descriptions.
Writes NOTHING. Reports: key count + singleton reduction vs current, every merge
group (to eyeball for WRONG merges), and confirms currently-grouped merchants
don't fragment. Iterate on CANDIDATE_RULES until the merges look right, then the
migration + unit test bake them in."""
import asyncio
from collections import defaultdict

from backend.config import load_config
from backend.database import close_pool, get_pool, init_pool
from backend.services.merchant_normalizer import MerchantNormalizer, build_normalizer

# New rules layered AFTER the current DB rules. (priority, pattern, replacement) —
# priority only documents intended order here; we append them post-DB-rules below.
CANDIDATE_RULES = [
    # --- Generic trailing-junk strippers run FIRST (so the anchored collapses
    #     below, which emit clean names, are never re-stripped). ---
    # Strip processor "future amount ~ tran" tails (Robinhood / Rocket Mortgage).
    (r"\s*~.*$", ""),
    # Strip trailing phone numbers (+ anything after).
    (r"\s+1?[-\s]?\(?\d{3}\)?[-\s]?\d{3}[-\s]?\d{4}\b.*$", ""),
    # Strip trailing 2-letter US state code.
    (r"\s+[A-Z]{2}\s*$", ""),
    # Cleanup: dangling trailing separators/space (incl. em/en dashes).
    (r"[\s\-–—]+$", ""),
    # --- Whole-merchant collapses (anchored) run LAST and are terminal. ---
    (r"^AMAZON\b.*$", "AMAZON"),
    (r"^GOOGLE\s*\*?\s*YOUTUBE TV.*$", "YOUTUBE TV"),
    (r"^GOOGLE\s*\*?\s*GOOGLE ONE.*$", "GOOGLE ONE"),
    (r"^GOOGLE\s*\*?\s*FI\b.*$", "GOOGLE FI"),
    (r"^WHOLE\s?F(OO)?DS\b.*$", "WHOLE FOODS"),
    (r"^WAL-?MART\s*\+?\s*MEMBER.*$", "WALMART+ MEMBER"),
    # Interest INCOME variants only — must NOT fold "Interest Charge on Purchases"
    # (a credit-card interest expense) in with interest earned (income).
    (r"^INTEREST(\s+(PAID|INCOME|PAYMENT|FOR)\b.*)?$", "INTEREST"),
    (r"^INVESTMENT ADMIN FEE.*$", "INVESTMENT ADMIN FEE"),
    (r"^INTERNET TRANSFER\b.*$", "INTERNET TRANSFER"),
]


async def main():
    await init_pool(load_config())
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            current = await build_normalizer(conn)
            current_rules = [(rx.pattern, repl) for rx, repl in current._rules]
            rows = await conn.fetch(
                "SELECT id, description, merchant_key FROM finance.transactions WHERE description IS NOT NULL")

        candidate = MerchantNormalizer(current_rules + CANDIDATE_RULES)

        old_keys = defaultdict(list)
        new_keys = defaultdict(list)
        for r in rows:
            old_keys[r["merchant_key"]].append(r["description"])
            new_keys[candidate.normalize(r["description"]).key].append(r["description"])

        def stats(d):
            singles = sum(1 for v in d.values() if len(v) == 1)
            return len(d), singles

        ok, os_ = stats(old_keys)
        nk, ns = stats(new_keys)
        print(f"CURRENT:  {ok} keys, {os_} singletons, {len(rows)} txns")
        print(f"CANDIDATE:{nk} keys, {ns} singletons  (Δ keys {nk-ok}, Δ singletons {ns-os_})\n")

        print("=== NEW merge groups (keys with >1 distinct description — eyeball for WRONG merges) ===")
        for key in sorted(new_keys):
            descs = sorted(set(new_keys[key]))
            if len(descs) > 1:
                print(f"\n[{key}]  ({len(new_keys[key])} txns, {len(descs)} distinct descr)")
                for d in descs[:8]:
                    print(f"    {d[:60]}")
                if len(descs) > 8:
                    print(f"    … +{len(descs)-8} more")
    finally:
        await close_pool()


asyncio.run(main())
