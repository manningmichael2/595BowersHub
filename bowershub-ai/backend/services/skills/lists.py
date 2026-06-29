"""Native skill: list management (shopping, to-do, packing, etc.)."""

from backend.services.skill_registry import native_skill


@native_skill("list", "lists", "shopping-list")
async def handle_list(params: dict) -> dict:
    """
    Manage lists. The AI determines the action from context.
    
    Params:
        action: "view", "add", "check", "remove", "clear", "all"
        list_name: which list (default: "shopping")
        items: list of item strings (for add/check/remove)
    """
    from backend.services.lists import (
        get_list, add_items, check_items, remove_items, clear_checked, get_all_lists
    )

    action = (params.get("action") or "view").lower().strip()
    list_name = params.get("list_name") or params.get("list") or "shopping"
    items = params.get("items") or []
    # The executor injects the acting user under "_user_id"; lists are
    # household-shared by default so this mainly attributes who created a list.
    user_id = params.get("_user_id") or 1

    # Handle string items (AI might pass a single string)
    if isinstance(items, str):
        items = [i.strip() for i in items.split(",") if i.strip()]

    if action == "all":
        return await get_all_lists(user_id=user_id)
    elif action in ("add", "create"):
        return await add_items(list_name, items, user_id=user_id)
    elif action in ("check", "done", "bought", "got", "purchased"):
        return await check_items(list_name, items, user_id=user_id)
    elif action in ("remove", "delete"):
        return await remove_items(list_name, items, user_id=user_id)
    elif action in ("clear", "clean"):
        return await clear_checked(list_name, user_id=user_id)
    else:
        # Default: view the list
        show_checked = params.get("show_checked", False)
        return await get_list(list_name, user_id=user_id, show_checked=show_checked)
