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


@native_skill("override-category")
async def handle_override_category(params: dict) -> dict:
    from backend.services.category_override import override_category

    return await override_category(
        transaction_id=params.get("transaction_id", ""),
        category_name=params.get("category_name", ""),
        create_if_missing=bool(params.get("create_if_missing", False)),
        confirm_retroactive=bool(params.get("confirm_retroactive", False)),
    )


@native_skill("list-files")
async def handle_list_files(params: dict) -> dict:
    from backend.services.finance import list_files

    return await list_files(path=params.get("path", "inbox"))
