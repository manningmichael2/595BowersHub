"""Lists API — household-shared shopping / to-do / packing lists.

Backs the Lists UI. The same `services.lists` layer powers the chat `list` skill;
these routes expose id-based item operations the UI needs (the chat path is
fuzzy-text). Lists are household-shared by default (see migration 0049), so any
authenticated member sees and edits the shared lists; the service enforces
per-item accessibility.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.middleware.auth import get_current_user
from backend.services import lists as svc

router = APIRouter(prefix="/api/lists", tags=["lists"])


class ItemsBody(BaseModel):
    model_config = {"extra": "forbid"}
    items: list[str]


class CheckedBody(BaseModel):
    model_config = {"extra": "forbid"}
    checked: bool


@router.get("")
async def all_lists(user: dict = Depends(get_current_user)) -> dict:
    """Every list the user can see (household-shared + their own) with counts."""
    return await svc.get_all_lists(user_id=user["id"])


@router.get("/{list_name}")
async def list_items(list_name: str, user: dict = Depends(get_current_user)) -> dict:
    """All items on a list (checked + unchecked), with ids."""
    return await svc.get_items(list_name, user_id=user["id"])


@router.post("/{list_name}/items")
async def add(list_name: str, body: ItemsBody, user: dict = Depends(get_current_user)) -> dict:
    """Add items (creates the list, shared by default, if absent)."""
    await svc.add_items(list_name, body.items, user_id=user["id"])
    return await svc.get_items(list_name, user_id=user["id"])


@router.put("/items/{item_id}")
async def set_checked(item_id: int, body: CheckedBody, user: dict = Depends(get_current_user)) -> dict:
    """Check/uncheck a single item by id."""
    ok = await svc.set_checked(item_id, body.checked, user_id=user["id"])
    return {"ok": ok}


@router.delete("/items/{item_id}")
async def remove_item(item_id: int, user: dict = Depends(get_current_user)) -> dict:
    """Delete a single item by id."""
    ok = await svc.delete_item(item_id, user_id=user["id"])
    return {"ok": ok}


@router.post("/{list_name}/clear")
async def clear_checked(list_name: str, user: dict = Depends(get_current_user)) -> dict:
    """Remove all checked-off items from a list."""
    await svc.clear_checked(list_name, user_id=user["id"])
    return await svc.get_items(list_name, user_id=user["id"])
