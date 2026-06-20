"""Typed Finance Review write API (R4).

Backs the Finance Review frontend (Task 12) and shares the same service layer the
chat skills use (R4.4). Every WRITE endpoint requires `Depends(require_admin)` —
`get_current_user` + an explicit owner/admin role check (MN4); the system is
single-owner today. Reads require an authenticated user.

Pydantic request/response models throughout — no `any` at the boundary (C6/R4.4).
DB-unavailable surfaces as a typed 503, never a partial write.
"""

from __future__ import annotations

import logging
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.database import get_pool
from backend.middleware.auth import get_current_user, require_admin
from backend.services.categorization.config import load_config
from backend.services.categorization.learning import record_correction
from backend.services.categorization.rules import apply_rule_to_existing

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/finance", tags=["finance-review"])


# --------------------------------------------------------------------------- models
class ReviewQueueItem(BaseModel):
    id: str
    description: Optional[str] = None
    amount: float
    posted_date: Optional[str] = None
    account_id: Optional[str] = None
    merchant_key: Optional[str] = None
    predicted_category_id: Optional[int] = None
    predicted_category_name: Optional[str] = None
    confidence: Optional[float] = None
    tier: Optional[str] = None
    transfer_suspected: bool = False
    rationale: Optional[dict] = None


class ReviewQueueResponse(BaseModel):
    items: list[ReviewQueueItem]
    count: int


class CategorizeRequest(BaseModel):
    category_id: int
    learn: bool = True  # reinforce merchant_memory (R3)


class CategorizeResponse(BaseModel):
    updated: int
    transaction_id: str
    category_id: int


class BulkCategorizeRequest(BaseModel):
    transaction_ids: list[str] = Field(min_length=1)
    category_id: int
    learn: bool = True


class BulkCategorizeResponse(BaseModel):
    updated: int
    requested: int


class ApplyMerchantRequest(BaseModel):
    category_id: int
    set_prior: bool = True       # set the directory category_prior_id (R3.3)
    make_rule: bool = False      # mint a user_rule for this merchant_key


class ApplyMerchantResponse(BaseModel):
    merchant_key: str
    updated: int
    rule_id: Optional[int] = None


class UserRuleModel(BaseModel):
    id: Optional[int] = None
    priority: int = 100
    category_id: int
    merchant_key: Optional[str] = None
    description_regex: Optional[str] = None
    amount_min: Optional[float] = None
    amount_max: Optional[float] = None
    account_id: Optional[str] = None
    is_active: bool = True


class CreateUserRuleRequest(UserRuleModel):
    apply_to_existing: bool = False


class CreateUserRuleResponse(BaseModel):
    rule: UserRuleModel
    applied: int = 0


class RecurringCharge(BaseModel):
    merchant_key: str
    occurrences: int
    avg_amount: float
    avg_interval_days: Optional[float] = None
    last_seen: Optional[str] = None


class RecurringResponse(BaseModel):
    charges: list[RecurringCharge]


# --------------------------------------------------------------------------- helpers
def _db_error(e: Exception) -> HTTPException:
    logger.warning("finance_review: DB unavailable: %s", e)
    return HTTPException(status_code=503, detail="Finance database unavailable; no changes were made.")


async def _category_exists(conn, category_id: int) -> bool:
    return await conn.fetchval("SELECT 1 FROM finance.categories WHERE id = $1", category_id) is not None


# --------------------------------------------------------------------------- read
@router.get("/review-queue", response_model=ReviewQueueResponse)
async def get_review_queue(limit: int = 100, offset: int = 0,
                           user: dict = Depends(get_current_user)) -> ReviewQueueResponse:
    """R4.1: uncategorized + below-threshold + "transfer?" items, each annotated
    with the latest decision-log prediction (category + confidence + rationale)."""
    limit = max(1, min(limit, 500))
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT t.id, t.description, t.amount, t.posted_date::text AS posted_date,
                       t.account_id, t.merchant_key,
                       d.applied_category_id AS predicted_category_id,
                       pc.name AS predicted_category_name,
                       d.confidence, d.tier, COALESCE(d.is_transfer_set, false) AS transfer_suspected,
                       d.rationale
                FROM finance.transactions t
                LEFT JOIN LATERAL (
                    SELECT applied_category_id, confidence, tier, is_transfer_set, rationale
                    FROM finance.categorization_decision cd
                    WHERE cd.transaction_id = t.id
                    ORDER BY cd.decided_at DESC LIMIT 1
                ) d ON true
                LEFT JOIN finance.categories pc ON pc.id = d.applied_category_id
                WHERE t.category_id IS NULL AND t.user_category_override = false
                  AND t.is_transfer = false AND t.is_investment = false
                ORDER BY t.posted_date DESC, t.id
                LIMIT $1 OFFSET $2
                """,
                limit, offset,
            )
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)
    items = [
        ReviewQueueItem(
            id=r["id"], description=r["description"], amount=float(r["amount"]),
            posted_date=r["posted_date"], account_id=r["account_id"],
            merchant_key=r["merchant_key"], predicted_category_id=r["predicted_category_id"],
            predicted_category_name=r["predicted_category_name"],
            confidence=float(r["confidence"]) if r["confidence"] is not None else None,
            tier=r["tier"], transfer_suspected=r["transfer_suspected"],
            rationale=r["rationale"],
        )
        for r in rows
    ]
    return ReviewQueueResponse(items=items, count=len(items))


@router.get("/recurring", response_model=RecurringResponse)
async def get_recurring(user: dict = Depends(get_current_user)) -> RecurringResponse:
    """R4.5: recurring charges — ≥ min_occurrences for a merchant_key, amounts
    within tolerance, with the average cadence. Live read-time query at this
    (single-household) volume; tolerances are DB config."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            cfg = await load_config(conn)
            rec = cfg.recurring
            rows = await conn.fetch(
                """
                WITH per_merchant AS (
                    SELECT merchant_key,
                           count(*) AS occurrences,
                           avg(amount) AS avg_amount,
                           stddev_pop(abs(amount)) AS amt_sd,
                           avg(abs(amount)) AS avg_abs,
                           max(posted_date)::text AS last_seen,
                           (max(posted_date) - min(posted_date))::float
                               / NULLIF(count(*) - 1, 0) AS avg_interval_days
                    FROM finance.transactions
                    WHERE merchant_key IS NOT NULL AND is_transfer = false AND amount < 0
                    GROUP BY merchant_key
                )
                SELECT merchant_key, occurrences, avg_amount, last_seen, avg_interval_days
                FROM per_merchant
                WHERE occurrences >= $1
                  AND (avg_abs = 0 OR COALESCE(amt_sd, 0) / NULLIF(avg_abs, 0) <= $2)
                ORDER BY occurrences DESC, merchant_key
                """,
                int(rec.get("min_occurrences", 3)),
                float(rec.get("amount_tolerance_pct", 15)) / 100.0,
            )
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)
    return RecurringResponse(charges=[
        RecurringCharge(
            merchant_key=r["merchant_key"], occurrences=r["occurrences"],
            avg_amount=float(r["avg_amount"]),
            avg_interval_days=float(r["avg_interval_days"]) if r["avg_interval_days"] is not None else None,
            last_seen=r["last_seen"],
        )
        for r in rows
    ])


@router.get("/user-rules", response_model=list[UserRuleModel])
async def list_user_rules(user: dict = Depends(get_current_user)) -> list[UserRuleModel]:
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, priority, category_id, merchant_key, description_regex, "
                "amount_min, amount_max, account_id, is_active FROM finance.user_rules "
                "ORDER BY priority, id")
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)
    return [
        UserRuleModel(
            id=r["id"], priority=r["priority"], category_id=r["category_id"],
            merchant_key=r["merchant_key"], description_regex=r["description_regex"],
            amount_min=float(r["amount_min"]) if r["amount_min"] is not None else None,
            amount_max=float(r["amount_max"]) if r["amount_max"] is not None else None,
            account_id=r["account_id"], is_active=r["is_active"],
        )
        for r in rows
    ]


# --------------------------------------------------------------------------- writes (RBAC)
@router.post("/transactions/{transaction_id}/categorize", response_model=CategorizeResponse)
async def categorize_transaction(transaction_id: str, body: CategorizeRequest,
                                 user: dict = Depends(require_admin)) -> CategorizeResponse:
    """R4.3: a human correction is authoritative — sets user_category_override and
    reinforces merchant_memory so it sticks (R3)."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                if not await _category_exists(conn, body.category_id):
                    raise HTTPException(status_code=404, detail="Category not found")
                row = await conn.fetchrow(
                    "SELECT category_id, merchant_key FROM finance.transactions WHERE id = $1",
                    transaction_id)
                if row is None:
                    raise HTTPException(status_code=404, detail="Transaction not found")
                res = await conn.execute(
                    "UPDATE finance.transactions SET category_id = $1, user_category_override = true, "
                    "categorized_by_tier = 'manual', categorization_confidence = 1.0, updated_at = now() "
                    "WHERE id = $2",
                    body.category_id, transaction_id)
                await conn.execute(
                    "INSERT INTO finance.categorization_decision (transaction_id, tier, confidence, "
                    "prior_category_id, applied_category_id, auto_applied, rationale) "
                    "VALUES ($1,'manual',1.0,$2,$3,true,$4::jsonb)",
                    transaction_id, row["category_id"], body.category_id, {"source": "review_api"})
                if body.learn and row["merchant_key"]:
                    await record_correction(conn, category_id=body.category_id,
                                            merchant_key=row["merchant_key"],
                                            transaction_id=transaction_id, source="review_api")
    except HTTPException:
        raise
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)
    return CategorizeResponse(updated=1 if res.endswith(" 1") else 0,
                              transaction_id=transaction_id, category_id=body.category_id)


@router.post("/transactions/bulk-categorize", response_model=BulkCategorizeResponse)
async def bulk_categorize(body: BulkCategorizeRequest,
                          user: dict = Depends(require_admin)) -> BulkCategorizeResponse:
    """R4.2: multi-select bulk apply. One transaction so the batch is all-or-nothing."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                if not await _category_exists(conn, body.category_id):
                    raise HTTPException(status_code=404, detail="Category not found")
                updated = 0
                for tid in body.transaction_ids:
                    row = await conn.fetchrow(
                        "SELECT category_id, merchant_key FROM finance.transactions WHERE id = $1", tid)
                    if row is None:
                        continue
                    res = await conn.execute(
                        "UPDATE finance.transactions SET category_id = $1, user_category_override = true, "
                        "categorized_by_tier = 'manual', categorization_confidence = 1.0, updated_at = now() "
                        "WHERE id = $2", body.category_id, tid)
                    await conn.execute(
                        "INSERT INTO finance.categorization_decision (transaction_id, tier, confidence, "
                        "prior_category_id, applied_category_id, auto_applied, rationale) "
                        "VALUES ($1,'manual',1.0,$2,$3,true,$4::jsonb)",
                        tid, row["category_id"], body.category_id, {"source": "review_api_bulk"})
                    if body.learn and row["merchant_key"]:
                        await record_correction(conn, category_id=body.category_id,
                                                merchant_key=row["merchant_key"],
                                                transaction_id=tid, source="review_api_bulk")
                    if res.endswith(" 1"):
                        updated += 1
    except HTTPException:
        raise
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)
    return BulkCategorizeResponse(updated=updated, requested=len(body.transaction_ids))


@router.post("/merchants/{merchant_key}/apply-category", response_model=ApplyMerchantResponse)
async def apply_merchant_category(merchant_key: str, body: ApplyMerchantRequest,
                                  user: dict = Depends(require_admin)) -> ApplyMerchantResponse:
    """R3.3/R4.3: gated mass-recategorization — apply a category to every
    (non-overridden) transaction for a merchant, reinforce learning, optionally set
    the directory prior and mint a rule. Each rewrite is logged with prior_category_id
    (reversible, R2.6)."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                if not await _category_exists(conn, body.category_id):
                    raise HTTPException(status_code=404, detail="Category not found")
                old = await conn.fetch(
                    "SELECT id, category_id FROM finance.transactions "
                    "WHERE merchant_key = $1 AND user_category_override = false", merchant_key)
                for r in old:
                    await conn.execute(
                        "INSERT INTO finance.categorization_decision (transaction_id, tier, confidence, "
                        "prior_category_id, applied_category_id, auto_applied, rationale) "
                        "VALUES ($1,'manual',1.0,$2,$3,true,$4::jsonb)",
                        r["id"], r["category_id"], body.category_id,
                        {"source": "apply_merchant", "merchant_key": merchant_key})
                res = await conn.execute(
                    "UPDATE finance.transactions SET category_id = $1, user_category_override = true, "
                    "categorized_by_tier = 'manual', categorization_confidence = 1.0, updated_at = now() "
                    "WHERE merchant_key = $2 AND user_category_override = false",
                    body.category_id, merchant_key)
                updated = int(res.split()[-1]) if res else 0

                await record_correction(conn, category_id=body.category_id,
                                        merchant_key=merchant_key, source="apply_merchant")
                if body.set_prior:
                    await conn.execute(
                        "INSERT INTO finance.merchants (merchant_key, display_name, category_prior_id) "
                        "VALUES ($1,$2,$3) ON CONFLICT (merchant_key) DO UPDATE "
                        "SET category_prior_id = EXCLUDED.category_prior_id, updated_at = now()",
                        merchant_key, merchant_key.title(), body.category_id)
                rule_id = None
                if body.make_rule:
                    rule_id = await conn.fetchval(
                        "INSERT INTO finance.user_rules (priority, category_id, merchant_key) "
                        "VALUES (100, $1, $2) RETURNING id", body.category_id, merchant_key)
    except HTTPException:
        raise
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)
    return ApplyMerchantResponse(merchant_key=merchant_key, updated=updated, rule_id=rule_id)


@router.post("/user-rules", response_model=CreateUserRuleResponse)
async def create_user_rule(body: CreateUserRuleRequest,
                           user: dict = Depends(require_admin)) -> CreateUserRuleResponse:
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                if not await _category_exists(conn, body.category_id):
                    raise HTTPException(status_code=404, detail="Category not found")
                rule_id = await conn.fetchval(
                    "INSERT INTO finance.user_rules (priority, category_id, merchant_key, "
                    "description_regex, amount_min, amount_max, account_id, is_active) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id",
                    body.priority, body.category_id, body.merchant_key, body.description_regex,
                    body.amount_min, body.amount_max, body.account_id, body.is_active)
                applied = 0
                if body.apply_to_existing:
                    applied = (await apply_rule_to_existing(conn, rule_id)).get("updated", 0)
                rule = UserRuleModel(id=rule_id, priority=body.priority, category_id=body.category_id,
                                     merchant_key=body.merchant_key, description_regex=body.description_regex,
                                     amount_min=body.amount_min, amount_max=body.amount_max,
                                     account_id=body.account_id, is_active=body.is_active)
    except HTTPException:
        raise
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)
    return CreateUserRuleResponse(rule=rule, applied=applied)


@router.delete("/user-rules/{rule_id}")
async def delete_user_rule(rule_id: int, user: dict = Depends(require_admin)) -> dict:
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            res = await conn.execute("DELETE FROM finance.user_rules WHERE id = $1", rule_id)
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)
    if res == "DELETE 0":
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"deleted": 1, "id": rule_id}
