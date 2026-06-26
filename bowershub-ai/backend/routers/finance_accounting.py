"""Typed Finance Accounting API (finance-accounting Task 8).

Net worth + history (reads), account list with reconcile status, manual transfer
link/unlink, reconcile, and set-account-type. Mirrors finance_review.py: Pydantic
in/out (no `any`), reads via get_current_user, mutations via require_admin, DB-down
→ typed 503. Shares services/accounting/ with the nightly jobs.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.database import get_pool
from backend.middleware.auth import require_capability
from backend.services.accounting.networth import compute_net_worth, net_worth_history
from backend.services.accounting.reconciliation import account_status, reconcile
from backend.services.accounting.transfers import TransferLinker
from backend.services.accounting.config import load_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/finance", tags=["finance-accounting"])

_ACCOUNT_TYPES = {"checking", "savings", "credit_card", "loan", "mortgage", "brokerage"}


# --------------------------------------------------------------------------- models
class AccountBalance(BaseModel):
    id: str
    name: str
    org: Optional[str] = None
    account_type: Optional[str] = None
    balance: float
    as_of: Optional[str] = None
    classification: str
    included: bool
    stale: bool


class NetWorthResponse(BaseModel):
    net_worth: float
    assets: float
    liabilities: float
    accounts: list[AccountBalance]


class NetWorthPoint(BaseModel):
    date: str
    net_worth: float


class NetWorthHistoryResponse(BaseModel):
    series: list[NetWorthPoint]


class LinkRequest(BaseModel):
    a_id: str
    b_id: str


class UnlinkRequest(BaseModel):
    id: str


class ReconcileRequest(BaseModel):
    statement_date: date
    statement_balance: float


class SetAccountTypeRequest(BaseModel):
    account_type: str = Field(pattern="^(checking|savings|credit_card|loan|mortgage|brokerage)$")


# --------------------------------------------------------------------------- helpers
def _db_error(e: Exception) -> HTTPException:
    logger.warning("finance_accounting: DB unavailable: %s", e)
    return HTTPException(status_code=503, detail="Finance database unavailable; no changes were made.")


# --------------------------------------------------------------------------- reads
@router.get("/net-worth", response_model=NetWorthResponse)
async def get_net_worth(user: dict = Depends(require_capability("finance.read"))) -> NetWorthResponse:
    try:
        async with get_pool().acquire() as conn:
            nw = await compute_net_worth(conn)
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)
    return NetWorthResponse(**nw)


@router.get("/net-worth/history", response_model=NetWorthHistoryResponse)
async def get_net_worth_history(days: int = 365, user: dict = Depends(require_capability("finance.read"))) -> NetWorthHistoryResponse:
    days = max(1, min(days, 3650))
    try:
        async with get_pool().acquire() as conn:
            series = await net_worth_history(conn, days=days)
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)
    return NetWorthHistoryResponse(series=[NetWorthPoint(**p) for p in series])


@router.get("/accounts/{account_id}/status")
async def get_account_status(account_id: str, user: dict = Depends(require_capability("finance.read"))) -> dict:
    try:
        async with get_pool().acquire() as conn:
            return await account_status(conn, account_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Account not found")
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)


@router.get("/accounts/{account_id}/reconciliations")
async def list_reconciliations(account_id: str, user: dict = Depends(require_capability("finance.read"))) -> dict:
    try:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, statement_date::text, statement_balance, synced_balance, delta, created_at::text "
                "FROM finance.reconciliations WHERE account_id = $1 ORDER BY statement_date DESC LIMIT 50",
                account_id)
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)
    return {"reconciliations": [dict(r) | {"statement_balance": float(r["statement_balance"]),
            "synced_balance": float(r["synced_balance"]) if r["synced_balance"] is not None else None,
            "delta": float(r["delta"]) if r["delta"] is not None else None} for r in rows]}


# --------------------------------------------------------------------------- writes (admin)
@router.post("/transactions/link")
async def link_transactions(body: LinkRequest, user: dict = Depends(require_capability("finance.write"))) -> dict:
    try:
        async with get_pool().acquire() as conn:
            cfg = await load_config(conn)
            return await TransferLinker(
                conn, amount_tolerance=cfg.match_amount_tolerance,
                date_window_days=cfg.match_date_window_days).link(body.a_id, body.b_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)


@router.post("/transactions/unlink")
async def unlink_transaction(body: UnlinkRequest, user: dict = Depends(require_capability("finance.write"))) -> dict:
    try:
        async with get_pool().acquire() as conn:
            return await TransferLinker(conn).unlink(body.id)
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)


@router.post("/accounts/{account_id}/reconcile")
async def reconcile_account(account_id: str, body: ReconcileRequest,
                            user: dict = Depends(require_capability("finance.write"))) -> dict:
    try:
        async with get_pool().acquire() as conn:
            return await reconcile(conn, account_id, body.statement_date, body.statement_balance)
    except LookupError:
        raise HTTPException(status_code=404, detail="Account not found")
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)


@router.put("/accounts/{account_id}/type")
async def set_account_type(account_id: str, body: SetAccountTypeRequest,
                           user: dict = Depends(require_capability("finance.delete"))) -> dict:
    """Operational path for account_type (R4.1): accounts arrive untyped from
    SimpleFin sync; net worth flags them "needs type" until set here."""
    try:
        async with get_pool().acquire() as conn:
            res = await conn.execute(
                "UPDATE finance.accounts SET account_type = $2 WHERE id = $1",
                account_id, body.account_type)
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)
    if not res.endswith(" 1"):
        raise HTTPException(status_code=404, detail="Account not found")
    return {"account_id": account_id, "account_type": body.account_type}
