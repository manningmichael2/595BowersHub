"""Native skills: finance — balances, transactions, spending, ask-db, override-category."""

from backend.services.skill_registry import native_skill


@native_skill("balances", "get-balances")
async def handle_balances(params: dict) -> dict:
    from backend.services.finance import get_balances

    return await get_balances()


@native_skill("transactions")
async def handle_transactions(params: dict) -> dict:
    from backend.services.transactions import get_transactions

    return await get_transactions(
        args=params.get("start_date") or params.get("query") or params.get("q", ""),
    )


@native_skill("filter-transactions")
async def handle_filter_transactions(params: dict) -> dict:
    from backend.services.finance import filter_transactions

    return await filter_transactions(
        account=params.get("account"),
        category=params.get("category"),
        description=params.get("description") or params.get("query"),
        min_amount=params.get("min_amount"),
        max_amount=params.get("max_amount"),
        start_date=params.get("start_date"),
        end_date=params.get("end_date"),
        limit=int(params.get("limit", 50)),
    )


@native_skill("spending-summary")
async def handle_spending_summary(params: dict) -> dict:
    from backend.services.finance import spending_summary

    return await spending_summary(month=params.get("month"))


@native_skill("ask-db", "finance-query")
async def handle_ask_db(params: dict) -> dict:
    from backend.services.finance import ask_db

    return await ask_db(
        question=params.get("question") or params.get("query") or params.get("q", ""),
    )


@native_skill("categorize-merchant")
async def handle_categorize_merchant(params: dict) -> dict:
    from backend.services.category_override import categorize_merchant
    return await categorize_merchant(
        description_pattern=params.get("description_pattern", ""),
        category_name=params.get("category_name", "")
    )


@native_skill("categorize-transaction")
async def handle_categorize_transaction(params: dict) -> dict:
    from backend.services.category_override import categorize_transaction
    return await categorize_transaction(
        transaction_id=params.get("transaction_id", ""),
        category_name=params.get("category_name", "")
    )


@native_skill("commit-bulk-update")
async def handle_commit_bulk_update(params: dict) -> dict:
    from backend.services.category_override import commit_bulk_update
    return await commit_bulk_update(
        description_pattern=params.get("description_pattern", ""),
        category_name=params.get("category_name", "")
    )


@native_skill("list-files")
async def handle_list_files(params: dict) -> dict:
    from backend.services.finance import list_files

    return await list_files(path=params.get("path", "inbox"))


@native_skill("run-categorizer")
async def handle_run_categorizer(params: dict) -> dict:
    from backend.services.categorizer import run_categorizer

    result = await run_categorizer()
    if result.get("status") == "skipped":
        return {"_display": "✅ No uncategorized transactions to process."}
    
    updated = result.get("updated", 0)
    found = result.get("transactions_found", 0)
    errors = result.get("errors", [])
    
    msg = f"✅ Categorizer completed. Processed {found} transactions, updated **{updated}** rows."
    if errors:
        msg += f"\n\n⚠️ Encountered {len(errors)} errors during processing."
        
    return {"_display": msg}
