"""Correct the immaterial mislabels from the first live cascade pass.

- Adds regex user_rules so recurring merchants auto-categorize correctly going
  forward (merchant_key is too noisy here — it's ~the full uppercased description,
  so each month's HealthEquity fee / Google One charge gets a distinct key).
- Corrects THIS run's already-applied rows (categorized_by_tier IS NOT NULL),
  setting user_category_override=true so the cascade won't re-touch them.
- The HealthEquity HSA 'Investment Admin Fee' is an investment-account fee, not
  Income → flag is_investment (consistent with how its sibling rows are treated)
  and clear the bad category.

Scoped by description + the categorized_by_tier guard so previously-categorized
history is never touched. Idempotent-ish (rules use ON CONFLICT-free guarded
inserts; row updates are naturally idempotent)."""
import asyncio

from backend.config import load_config
from backend.database import close_pool, get_pool, init_pool


# (description ILIKE pattern, target leaf category) for this run's applied rows.
ROW_FIXES = [
    ("%ANTHROPIC%", "Subscriptions"),
    ("%GOOGLE%GOOGLE ONE%", "Subscriptions"),
    ("Uber Trip%", "Trans_Public_Transit"),
    ("ZEL FROM MANON NITTA%", "Income"),
]
# (description_regex, target leaf category, priority) — auto-fix future occurrences.
RULE_FIXES = [
    ("ANTHROPIC", "Subscriptions", 10),
    (r"GOOGLE.*GOOGLE ONE", "Subscriptions", 10),
    ("UBER TRIP", "Trans_Public_Transit", 10),
]


async def main():
    await init_pool(load_config())
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            async def cat_id(name):
                cid = await conn.fetchval("SELECT id FROM finance.categories WHERE name=$1", name)
                assert cid is not None, f"missing category {name}"
                return cid

            # 1. Regex user_rules (skip if an identical active rule already exists).
            for regex, cat, prio in RULE_FIXES:
                cid = await cat_id(cat)
                exists = await conn.fetchval(
                    "SELECT 1 FROM finance.user_rules WHERE description_regex=$1 AND category_id=$2 AND is_active",
                    regex, cid)
                if exists:
                    print(f"rule exists: /{regex}/ -> {cat}", flush=True)
                    continue
                await conn.execute(
                    "INSERT INTO finance.user_rules (priority, description_regex, category_id, is_active) "
                    "VALUES ($1,$2,$3,true)", prio, regex, cid)
                print(f"rule added:  /{regex}/ -> {cat}", flush=True)

            # 2. Correct this run's applied rows (sticky via override).
            for pat, cat in ROW_FIXES:
                cid = await cat_id(cat)
                res = await conn.execute(
                    "UPDATE finance.transactions "
                    "SET category_id=$1, user_category_override=true, "
                    "    categorization_confidence=NULL, categorized_by_tier='manual', updated_at=now() "
                    "WHERE description ILIKE $2 AND categorized_by_tier IS NOT NULL "
                    "  AND categorized_by_tier <> 'manual'",
                    cid, pat)
                print(f"row fix: {pat!r:38s} -> {cat:22s} {res}", flush=True)

            # 3. HealthEquity HSA admin fee: investment-account fee, not Income.
            res = await conn.execute(
                "UPDATE finance.transactions "
                "SET is_investment=true, category_id=NULL, categorization_confidence=NULL, "
                "    categorized_by_tier=NULL, updated_at=now() "
                "WHERE description ILIKE '%INVESTMENT ADMIN FEE%HEALTHEQUITY%' "
                "  AND categorized_by_tier IS NOT NULL")
            print(f"hsa fee -> is_investment {res}", flush=True)

            # Report final state of the corrected rows.
            print("\n-- after --", flush=True)
            rows = await conn.fetch(
                "SELECT COALESCE(c.name,'(investment)') cat, t.is_investment inv, t.amount, left(t.description,42) d "
                "FROM finance.transactions t LEFT JOIN finance.categories c ON c.id=t.category_id "
                "WHERE t.description ILIKE '%ANTHROPIC%' OR t.description ILIKE '%GOOGLE%GOOGLE ONE%' "
                "   OR t.description ILIKE 'Uber Trip%' OR t.description ILIKE 'ZEL FROM MANON%' "
                "   OR t.description ILIKE '%INVESTMENT ADMIN FEE%HEALTHEQUITY%' "
                "ORDER BY cat")
            for r in rows:
                print(f"   {r['cat']:22s} inv={r['inv']} {float(r['amount']):>9.2f}  {r['d']}", flush=True)
    finally:
        await close_pool()


asyncio.run(main())
