"""Native skill: list management (shopping, to-do, gifts, packing, chores, etc.)."""

from backend.services.skill_registry import native_skill


@native_skill("list", "lists", "shopping-list")
async def handle_list(params: dict) -> dict:
    """
    Manage lists. The AI determines the action from context.

    Params:
        action: "view", "add", "check", "remove", "clear", "all"
        list_name: which list (optional — for "add" the router picks the right
            existing list when this is omitted; there is no hardcoded default)
        items: list of item strings (for add/check/remove)
    """
    from backend.services.lists import (
        get_list, check_items, remove_items, clear_checked, get_all_lists,
    )
    from backend.services import list_router

    action = (params.get("action") or "view").lower().strip()
    list_name = params.get("list_name") or params.get("list")    # no "shopping" default
    items = params.get("items") or []
    # The executor injects the acting user under "_user_id"; lists are
    # household-shared by default so this mainly attributes who created a list.
    user_id = params.get("_user_id") or 1

    if isinstance(items, str):
        items = [i.strip() for i in items.split(",") if i.strip()]

    if action == "all":
        return await get_all_lists(user_id=user_id)
    elif action in ("add", "create"):
        # Route each item to the right existing list (or the elected default);
        # never auto-creates a list from a misheard name (R4.3).
        result = await list_router.route_and_add(items, user_id, explicit_list=list_name)
        return _format_add(result)
    elif action in ("check", "done", "bought", "got", "purchased"):
        return await check_items(list_name or "", items, user_id=user_id)
    elif action in ("remove", "delete"):
        return await remove_items(list_name or "", items, user_id=user_id)
    elif action in ("clear", "clean"):
        return await clear_checked(list_name or "", user_id=user_id)
    else:
        show_checked = params.get("show_checked", False)
        return await get_list(list_name or "", user_id=user_id, show_checked=show_checked)


def _format_add(result: dict) -> dict:
    parts = []
    for entry in result.get("added", []):
        if entry["added"]:
            parts.append("✅ Added " + ", ".join(f"**{a}**" for a in entry["added"]))
    for q in result.get("needs_disambiguation", []):
        opts = " or ".join(q["candidates"])
        parts.append(f"❓ Which list for **{q['text']}** — {opts}?")
    if not parts:
        parts.append("Nothing to add.")
    return {**result, "_display": "\n".join(parts)}
