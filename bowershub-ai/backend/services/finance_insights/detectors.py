"""The six insight detectors (R2.2, R2.3).

Each detector runs parameterized read-only SQL over the allocation-aware
`public.real_activity` view (joined to `finance.transactions` for `merchant_key`
/ descriptions, which the view omits) plus the shared recurring detection, applies
a robust statistic (median/MAD or IQR) with a minimum-history guard, and emits
`Candidate`s carrying both the figures and a human-readable reason (explainable —
R2.3). Detectors are registered as a light `(type, config_key, fn)` list, not a
framework (the design rejected a heavy registry).

Detectors run as the app/migrator pool (internal nightly job), so they read
`finance.transactions` directly — they are NOT the `finance_reader` Q&A sandbox.
All thresholds come from `finance.insight_config` via the loaded `InsightConfig`.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Dict, List

from .config import InsightConfig
from .recurring import recurring_charges


@dataclass
class Candidate:
    insight_type: str
    merchant_key: str          # grouping key: a merchant_key, or "category:<id>"/"account:<id>"
    period: str                # YYYY-MM of the triggering activity
    dollar_impact: float
    figures: Dict[str, Any]
    reason: str


@dataclass
class Detector:
    insight_type: str
    config_key: str            # the detector.<key>.* config namespace + enable flag
    fn: Callable               # async (conn, cfg) -> List[Candidate]


def _f(x: Any) -> float:
    return float(x) if isinstance(x, Decimal) else float(x)


def _ym(d: date) -> str:
    return d.strftime("%Y-%m")


def _dedupe(cands: List[Candidate]) -> List[Candidate]:
    """One candidate per (type, merchant, period); keep the largest impact."""
    best: Dict[tuple, Candidate] = {}
    for c in cands:
        key = (c.insight_type, c.merchant_key, c.period)
        if key not in best or c.dollar_impact > best[key].dollar_impact:
            best[key] = c
    return list(best.values())


# --- 1. duplicate-charge ----------------------------------------------------

async def detect_duplicate_charge(conn, cfg: InsightConfig) -> List[Candidate]:
    window = int(cfg.get("detector.duplicate_charge.window_days"))
    tol = float(cfg.get("detector.duplicate_charge.amount_tolerance"))
    rows = await conn.fetch(
        """
        SELECT t1.merchant_key, t1.amount AS amount,
               t1.posted_date AS d1, t2.posted_date AS d2
        FROM public.real_activity ra1
        JOIN finance.transactions t1 ON t1.id = ra1.id
        JOIN finance.transactions t2 ON t2.merchant_key = t1.merchant_key AND t2.id <> t1.id
        JOIN public.real_activity ra2 ON ra2.id = t2.id
        WHERE t1.merchant_key IS NOT NULL
          AND t1.amount < 0
          AND abs(t1.amount - t2.amount) <= $1
          AND t2.posted_date >= t1.posted_date
          AND t2.posted_date <= t1.posted_date + $2::int
          AND t1.id < t2.id
        """,
        tol, window,
    )
    cands = []
    for r in rows:
        amt = abs(_f(r["amount"]))
        cands.append(Candidate(
            insight_type="duplicate_charge",
            merchant_key=r["merchant_key"],
            period=_ym(r["d2"]),
            dollar_impact=amt,
            figures={"amount": amt, "first_date": r["d1"].isoformat(),
                     "second_date": r["d2"].isoformat(), "window_days": window},
            reason=(f"Two charges of ${amt:,.2f} at {r['merchant_key']} within "
                    f"{window} days ({r['d1'].isoformat()} and {r['d2'].isoformat()}) "
                    f"— possible duplicate."),
        ))
    return _dedupe(cands)


# --- 2. price-creep ---------------------------------------------------------

async def detect_price_creep(conn, cfg: InsightConfig) -> List[Candidate]:
    min_history = int(cfg.get("detector.price_creep.min_history"))
    min_pct = float(cfg.get("detector.price_creep.min_increase_pct"))
    rows = await conn.fetch(
        """
        WITH charges AS (
            SELECT t.merchant_key, t.posted_date, abs(t.amount) AS amt,
                   row_number() OVER (PARTITION BY t.merchant_key
                                      ORDER BY t.posted_date DESC, t.id DESC) AS rn,
                   count(*) OVER (PARTITION BY t.merchant_key) AS n
            FROM public.real_activity ra
            JOIN finance.transactions t ON t.id = ra.id
            WHERE t.merchant_key IS NOT NULL AND t.amount < 0
        )
        SELECT merchant_key,
               max(CASE WHEN rn = 1 THEN amt END) AS latest,
               avg(CASE WHEN rn > 1 THEN amt END) AS prior_avg,
               max(CASE WHEN rn = 1 THEN posted_date END) AS latest_date,
               max(n) AS n
        FROM charges
        GROUP BY merchant_key
        HAVING max(n) >= $1
        """,
        min_history,
    )
    cands = []
    for r in rows:
        prior = r["prior_avg"]
        latest = r["latest"]
        if prior is None or latest is None or _f(prior) <= 0:
            continue
        prior_f, latest_f = _f(prior), _f(latest)
        if latest_f >= prior_f * (1 + min_pct):
            cands.append(Candidate(
                insight_type="price_creep",
                merchant_key=r["merchant_key"],
                period=_ym(r["latest_date"]),
                dollar_impact=round(latest_f - prior_f, 2),
                figures={"latest": round(latest_f, 2), "prior_avg": round(prior_f, 2),
                         "pct_increase": round((latest_f / prior_f - 1) * 100, 1),
                         "history": int(r["n"])},
                reason=(f"{r['merchant_key']} rose to ${latest_f:,.2f} from a prior "
                        f"average of ${prior_f:,.2f} "
                        f"(+{(latest_f / prior_f - 1) * 100:.0f}%)."),
            ))
    return _dedupe(cands)


# --- 3. free-trial-conversion ----------------------------------------------

async def detect_free_trial_conversion(conn, cfg: InsightConfig) -> List[Candidate]:
    lookback = int(cfg.get("detector.free_trial_conversion.lookback_days"))
    min_amount = float(cfg.get("detector.free_trial_conversion.min_amount"))
    rows = await conn.fetch(
        """
        SELECT t.merchant_key, min(t.posted_date) AS first_date,
               max(t.posted_date) AS last_date, count(*) AS n, max(abs(t.amount)) AS amt
        FROM public.real_activity ra
        JOIN finance.transactions t ON t.id = ra.id
        WHERE t.merchant_key IS NOT NULL AND t.amount < 0
        GROUP BY t.merchant_key
        HAVING min(t.posted_date) >= CURRENT_DATE - $1::int
           AND max(abs(t.amount)) >= $2
        """,
        lookback, min_amount,
    )
    cands = []
    for r in rows:
        amt = _f(r["amt"])
        cands.append(Candidate(
            insight_type="free_trial_conversion",
            merchant_key=r["merchant_key"],
            period=_ym(r["first_date"]),
            dollar_impact=round(amt, 2),
            figures={"first_charge": r["first_date"].isoformat(), "amount": round(amt, 2),
                     "occurrences": int(r["n"]), "lookback_days": lookback},
            reason=(f"New charge at {r['merchant_key']} of ${amt:,.2f} started "
                    f"{r['first_date'].isoformat()} — check it isn't a trial that "
                    f"converted to paid."),
        ))
    return _dedupe(cands)


# --- 4. unusual-spend (category monthly, median/MAD) ------------------------

async def detect_unusual_spend(conn, cfg: InsightConfig) -> List[Candidate]:
    min_history = int(cfg.get("detector.unusual_spend.min_history"))
    mult = float(cfg.get("detector.unusual_spend.mad_multiplier"))
    rows = await conn.fetch(
        """
        SELECT ra.category_id,
               to_char(date_trunc('month', ra.posted_date), 'YYYY-MM') AS ym,
               sum(abs(ra.amount)) AS spent
        FROM public.real_activity ra
        WHERE ra.amount < 0 AND ra.category_id IS NOT NULL
        GROUP BY ra.category_id, ym
        ORDER BY ra.category_id, ym
        """
    )
    by_cat: Dict[int, List[tuple]] = {}
    for r in rows:
        by_cat.setdefault(r["category_id"], []).append((r["ym"], _f(r["spent"])))

    cands = []
    for category_id, series in by_cat.items():
        if len(series) < min_history + 1:        # need >= min_history PRIOR months
            continue
        series.sort()                             # by ym ascending
        *prior, current = series
        prior_vals = [v for _, v in prior]
        cur_ym, cur_val = current
        med = statistics.median(prior_vals)
        mad = statistics.median([abs(v - med) for v in prior_vals])
        # Guard a zero-MAD (flat history): require a strictly higher current.
        if mad <= 0:
            continue
        if abs(cur_val - med) > mult * mad and cur_val > med:
            cands.append(Candidate(
                insight_type="unusual_spend",
                merchant_key=f"category:{category_id}",
                period=cur_ym,
                dollar_impact=round(cur_val - med, 2),
                figures={"current": round(cur_val, 2), "median": round(med, 2),
                         "mad": round(mad, 2), "months_history": len(prior_vals),
                         "category_id": category_id},
                reason=(f"Category {category_id} spend of ${cur_val:,.2f} in {cur_ym} "
                        f"is well above its typical ${med:,.2f}."),
            ))
    return _dedupe(cands)


# --- 5. bill-higher-than-usual (recurring bill, IQR fence) ------------------

def _quartiles(values: List[float]) -> tuple:
    """(Q1, Q3) via the inclusive method; needs >= 2 points."""
    qs = statistics.quantiles(values, n=4, method="inclusive")
    return qs[0], qs[2]


async def detect_bill_higher_than_usual(conn, cfg: InsightConfig) -> List[Candidate]:
    min_history = int(cfg.get("detector.bill_higher_than_usual.min_history"))
    mult = float(cfg.get("detector.bill_higher_than_usual.iqr_multiplier"))
    rows = await conn.fetch(
        """
        SELECT t.merchant_key, abs(t.amount) AS amt, t.posted_date,
               row_number() OVER (PARTITION BY t.merchant_key
                                  ORDER BY t.posted_date DESC, t.id DESC) AS rn
        FROM public.real_activity ra
        JOIN finance.transactions t ON t.id = ra.id
        WHERE t.merchant_key IS NOT NULL AND t.amount < 0
        ORDER BY t.merchant_key
        """
    )
    by_merchant: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        m = by_merchant.setdefault(r["merchant_key"], {"amts": [], "latest": None, "latest_date": None})
        m["amts"].append(_f(r["amt"]))
        if r["rn"] == 1:
            m["latest"] = _f(r["amt"])
            m["latest_date"] = r["posted_date"]

    cands = []
    for merchant, m in by_merchant.items():
        amts = m["amts"]
        if len(amts) < min_history:
            continue
        q1, q3 = _quartiles(amts)
        fence = q3 + mult * (q3 - q1)
        latest = m["latest"]
        if latest is not None and (q3 - q1) > 0 and latest > fence:
            cands.append(Candidate(
                insight_type="bill_higher_than_usual",
                merchant_key=merchant,
                period=_ym(m["latest_date"]),
                dollar_impact=round(latest - q3, 2),
                figures={"latest": round(latest, 2), "q1": round(q1, 2), "q3": round(q3, 2),
                         "fence": round(fence, 2), "history": len(amts)},
                reason=(f"{merchant} bill of ${latest:,.2f} is above its usual range "
                        f"(typical ${q1:,.2f}–${q3:,.2f})."),
            ))
    return _dedupe(cands)


# --- 6. low-balance-before-payday ------------------------------------------

async def detect_low_balance_before_payday(conn, cfg: InsightConfig) -> List[Candidate]:
    floor = float(cfg.get("detector.low_balance_before_payday.floor"))
    rows = await conn.fetch(
        """
        SELECT id, account_name, last_balance, last_balance_date
        FROM finance.accounts
        WHERE last_balance IS NOT NULL
          AND last_balance < $1
          AND include_in_net_worth = true
        """,
        floor,
    )
    cands = []
    for r in rows:
        bal = _f(r["last_balance"])
        when = r["last_balance_date"] or date.today()
        cands.append(Candidate(
            insight_type="low_balance_before_payday",
            merchant_key=f"account:{r['id']}",
            period=_ym(when),
            dollar_impact=round(floor - bal, 2),
            figures={"balance": round(bal, 2), "floor": floor,
                     "account": r["account_name"], "as_of": when.isoformat()},
            reason=(f"{r['account_name'] or r['id']} balance is ${bal:,.2f}, below the "
                    f"${floor:,.0f} floor — watch for upcoming bills before payday."),
        ))
    return _dedupe(cands)


# --- registry (light list, not a framework) --------------------------------

DETECTORS: List[Detector] = [
    Detector("duplicate_charge", "duplicate_charge", detect_duplicate_charge),
    Detector("price_creep", "price_creep", detect_price_creep),
    Detector("free_trial_conversion", "free_trial_conversion", detect_free_trial_conversion),
    Detector("unusual_spend", "unusual_spend", detect_unusual_spend),
    Detector("bill_higher_than_usual", "bill_higher_than_usual", detect_bill_higher_than_usual),
    Detector("low_balance_before_payday", "low_balance_before_payday", detect_low_balance_before_payday),
]


async def run_detectors(conn, cfg: InsightConfig) -> List[Candidate]:
    """Run every ENABLED detector and return the combined candidate list. A single
    detector raising must not sink the rest — the runner records the failure."""
    out: List[Candidate] = []
    for det in DETECTORS:
        if not cfg.enabled(det.config_key):
            continue
        out.extend(await det.fn(conn, cfg))
    return out
