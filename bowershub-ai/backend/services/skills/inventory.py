"""Native skills: inventory browsing and admin."""

import json as _json
from backend.services.skill_registry import native_skill


@native_skill("inventory")
async def handle_inventory(params: dict) -> dict:
    from backend.services.inventory import get_inventory

    return await get_inventory(
        table=params.get("table") or params.get("query") or params.get("q", ""),
    )


@native_skill("inventory-admin")
async def handle_inventory_admin(params: dict) -> dict:
    from backend.services.inventory_admin import inventory_admin

    # Parse fields if string
    fields = params.get("fields")
    if isinstance(fields, str):
        try:
            fields = _json.loads(fields)
        except Exception:
            fields = None

    return await inventory_admin(
        action=params.get("action", ""),
        table=params.get("table", ""),
        id=int(params["id"]) if params.get("id") else None,
        fields=fields,
        merge_into_id=int(params["merge_into_id"]) if params.get("merge_into_id") else None,
        column_name=params.get("column_name"),
        column_type=params.get("column_type"),
    )
