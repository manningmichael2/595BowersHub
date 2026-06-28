"""Transactions explorer API (Monarch/Origin-style). A single flexible read
endpoint backing the unified Finance → Transactions view: filter (text/category/
month/account/status), sort, paginate, with allocation-aware subtotals + totals.
Read-only; auth via get_current_user; DB-down → typed 503.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_pool
from backend.middleware.auth import get_current_user
from backend.services.transactions_query import search_transactions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/finance", tags=["finance-transactions"])

_STATUSES = {"all", "uncategorized", "spending", "income", "transfers"}


@router.get("/transactions")
async def list_transactions(
    q: Optional[str] = None,
    category_id: Optional[int] = None,
    month: Optional[date] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
    account_id: Optional[str] = None,
    owner: Optional[str] = None,
    status: str = "all",
    sort: str = "date",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
    user: dict = Depends(get_current_user),
) -> dict:
    if status not in _STATUSES:
        raise HTTPException(status_code=400, detail=f"invalid status; one of {sorted(_STATUSES)}")
    try:
        async with get_pool().acquire() as conn:
            return await search_transactions(
                conn, q=q, category_id=category_id,
                month=month.replace(day=1) if month else None,
                start=start, end=end,
                account_id=account_id, owner=owner, status=status,
                sort=sort, order=order,
                limit=limit, offset=offset)
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        logger.warning("finance_transactions: DB unavailable: %s", e)
        raise HTTPException(status_code=503, detail="Finance database unavailable.")
