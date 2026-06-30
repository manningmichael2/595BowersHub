"""Lists API — generic typed-list handler (lists-v2).

ID-addressed routes are authoritative; name-addressed routes are retained as
back-compat shims so a cached PWA keeps working during the cutover. The UI
name-POST shim still creates-on-add (an explicit user action); the AI/chat path
goes through services.list_router and never auto-creates. Lists are
household-shared by default; the service enforces per-list / per-item access.

Route ORDER matters: literal paths and the int-converter list routes are
registered before the `/{list_name}` string shim so they win.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.middleware.auth import get_current_user
from backend.services import lists as svc
from backend.services import list_config as cfg
from backend.services import list_grouping
from backend.services import list_schema
from backend.services.lists import ListError
from backend.services.list_schema import ListSchemaError

router = APIRouter(prefix="/api/lists", tags=["lists"])


# ── Bodies ───────────────────────────────────────────────────────────────────

class CreateListBody(BaseModel):
    model_config = {"extra": "forbid"}
    name: str
    list_type_id: Optional[int] = None
    is_shared: bool = True


class PatchListBody(BaseModel):
    model_config = {"extra": "forbid"}
    name: Optional[str] = None
    list_type_id: Optional[int] = None


class AddItemsBody(BaseModel):
    model_config = {"extra": "forbid"}
    items: list[Any]                      # str or {text, category, attributes, ...}


class CheckedBody(BaseModel):
    model_config = {"extra": "forbid"}
    checked: bool


class PatchItemBody(BaseModel):
    model_config = {"extra": "allow"}     # allow attribute keys
    checked: Optional[bool] = None
    text: Optional[str] = None
    category: Optional[str] = None
    sort_order: Optional[float] = None


class ReorderBody(BaseModel):
    model_config = {"extra": "forbid"}
    ordered_item_ids: list[int]


class MoveBody(BaseModel):
    model_config = {"extra": "forbid"}
    item_id: int
    before_id: Optional[int] = None
    after_id: Optional[int] = None


class CreateFieldBody(BaseModel):
    model_config = {"extra": "forbid"}
    key: str
    label: str
    col_type: str
    options: Optional[list] = None
    required: bool = False


class PatchFieldBody(BaseModel):
    model_config = {"extra": "forbid"}
    label: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    options: Optional[list] = None


class StoreBody(BaseModel):
    model_config = {"extra": "forbid"}
    name: str


class PatchStoreBody(BaseModel):
    model_config = {"extra": "forbid"}
    name: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class AislesBody(BaseModel):
    model_config = {"extra": "forbid"}
    departments: list[str]


# ── Literal collection / config routes (registered first) ─────────────────────

@router.get("")
async def all_lists(user: dict = Depends(get_current_user)) -> dict:
    return await svc.get_all_lists(user_id=user["id"])


@router.post("")
async def create_list(body: CreateListBody, user: dict = Depends(get_current_user)) -> dict:
    pool = svc.get_pool()
    try:
        async with pool.acquire() as conn:
            list_id = await svc.create_list(conn, body.name, user["id"],
                                            body.list_type_id, body.is_shared)
    except ListError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"id": list_id}


@router.get("/types")
async def get_types(user: dict = Depends(get_current_user)) -> dict:
    return {"types": await cfg.list_types()}


@router.get("/config")
async def get_config(user: dict = Depends(get_current_user)) -> dict:
    return await cfg.config()


@router.get("/stores")
async def get_stores(user: dict = Depends(get_current_user)) -> dict:
    return {"stores": await cfg.list_stores()}


@router.post("/stores")
async def add_store(body: StoreBody, user: dict = Depends(get_current_user)) -> dict:
    try:
        return await cfg.create_store(body.name, user["id"])
    except ListError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.patch("/stores/{store_id}")
async def patch_store(store_id: int, body: PatchStoreBody,
                      user: dict = Depends(get_current_user)) -> dict:
    ok = await cfg.update_store(store_id, name=body.name, sort_order=body.sort_order,
                                is_active=body.is_active)
    return {"ok": ok}


@router.delete("/stores/{store_id}")
async def remove_store(store_id: int, user: dict = Depends(get_current_user)) -> dict:
    return {"ok": await cfg.delete_store(store_id)}


@router.put("/stores/{store_id}/aisles")
async def put_aisles(store_id: int, body: AislesBody,
                     user: dict = Depends(get_current_user)) -> dict:
    return {"ok": await cfg.set_store_aisles(store_id, body.departments)}


# ── Item-by-id routes (literal "items" prefix) ────────────────────────────────

@router.put("/items/{item_id}")
async def check_item(item_id: int, body: CheckedBody,
                     user: dict = Depends(get_current_user)) -> dict:
    return {"ok": await svc.set_checked(item_id, body.checked, user_id=user["id"])}


@router.patch("/items/{item_id}")
async def patch_item(item_id: int, body: PatchItemBody,
                     user: dict = Depends(get_current_user)) -> dict:
    changes = dict(body.model_dump(exclude_unset=True))
    try:
        ok = await svc.update_item(item_id, changes, user_id=user["id"])
    except ListSchemaError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": ok}


@router.delete("/items/{item_id}")
async def remove_item(item_id: int, user: dict = Depends(get_current_user)) -> dict:
    return {"ok": await svc.delete_item(item_id, user_id=user["id"])}


# ── List-by-id routes (int converter; registered before the name shim) ────────

@router.get("/{list_id:int}")
async def get_list(list_id: int, user: dict = Depends(get_current_user)) -> dict:
    data = await svc.get_items_by_id(list_id, user_id=user["id"])
    if data is None:
        raise HTTPException(status_code=404, detail="List not found")
    pool = svc.get_pool()
    async with pool.acquire() as conn:
        schema = await list_schema.resolve_schema(conn, list_id)
    data["schema"] = [list_schema.field_to_dict(f) for f in schema.fields]
    return data


@router.get("/{list_id:int}/view")
async def grouped_view(list_id: int,
                       store: Optional[str] = Query(None),
                       sort: Optional[str] = Query(None),
                       group: bool = Query(True),
                       category: Optional[str] = Query(None),
                       assignee_user_id: Optional[int] = Query(None),
                       checked: Optional[bool] = Query(None),
                       user: dict = Depends(get_current_user)) -> dict:
    """Grouped/sorted/filtered view of a list (R5.1–R5.6)."""
    pool = svc.get_pool()
    async with pool.acquire() as conn:
        if not await svc._list_accessible(conn, list_id, user["id"]):
            raise HTTPException(status_code=404, detail="List not found")
        view = await list_grouping.grouped_view(
            conn, list_id, store=store, sort=sort, group=group,
            filters={"category": category, "assignee_user_id": assignee_user_id, "checked": checked})
        schema = await list_schema.resolve_schema(conn, list_id)
    view["schema"] = [list_schema.field_to_dict(f) for f in schema.fields]
    return view


@router.patch("/{list_id:int}")
async def patch_list(list_id: int, body: PatchListBody,
                     user: dict = Depends(get_current_user)) -> dict:
    try:
        if body.name is not None:
            if not await svc.rename_list(list_id, body.name, user["id"]):
                raise HTTPException(status_code=404, detail="List not found")
        if body.list_type_id is not None:
            await svc.set_list_type(list_id, body.list_type_id, user["id"])
    except ListError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True}


@router.delete("/{list_id:int}")
async def delete_list(list_id: int, confirm: bool = Query(False),
                      user: dict = Depends(get_current_user)) -> dict:
    if not confirm:
        raise HTTPException(status_code=400, detail="Pass ?confirm=true to delete a list")
    return {"ok": await svc.delete_list(list_id, user["id"])}


@router.post("/{list_id:int}/items")
async def add_items_by_id(list_id: int, body: AddItemsBody,
                          user: dict = Depends(get_current_user)) -> dict:
    try:
        await svc.add_items_by_id(list_id, body.items, user_id=user["id"])
    except ListError:
        raise HTTPException(status_code=404, detail="List not found")
    except ListSchemaError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return await get_list(list_id, user)


@router.post("/{list_id:int}/items/reorder")
async def reorder_items(list_id: int, body: ReorderBody,
                        user: dict = Depends(get_current_user)) -> dict:
    return {"ok": await svc.reorder(list_id, body.ordered_item_ids, user["id"])}


@router.post("/{list_id:int}/move")
async def move(list_id: int, body: MoveBody, user: dict = Depends(get_current_user)) -> dict:
    return {"ok": await svc.move_item(body.item_id, body.before_id, body.after_id, user["id"])}


@router.post("/{list_id:int}/clear")
async def clear_by_id(list_id: int, user: dict = Depends(get_current_user)) -> dict:
    n = await svc.clear_checked_by_id(list_id, user["id"])
    if n < 0:
        raise HTTPException(status_code=404, detail="List not found")
    return await get_list(list_id, user)


@router.post("/{list_id:int}/archive")
async def archive(list_id: int, user: dict = Depends(get_current_user)) -> dict:
    return {"ok": await svc.set_archived(list_id, True, user["id"])}


@router.post("/{list_id:int}/unarchive")
async def unarchive(list_id: int, user: dict = Depends(get_current_user)) -> dict:
    return {"ok": await svc.set_archived(list_id, False, user["id"])}


@router.get("/{list_id:int}/fields")
async def get_fields(list_id: int, user: dict = Depends(get_current_user)) -> dict:
    pool = svc.get_pool()
    async with pool.acquire() as conn:
        if not await svc._list_accessible(conn, list_id, user["id"]):
            raise HTTPException(status_code=404, detail="List not found")
        schema = await list_schema.resolve_schema(conn, list_id)
    return {"fields": [list_schema.field_to_dict(f) for f in schema.fields]}


@router.post("/{list_id:int}/fields")
async def add_field(list_id: int, body: CreateFieldBody,
                    user: dict = Depends(get_current_user)) -> dict:
    pool = svc.get_pool()
    async with pool.acquire() as conn:
        if not await svc._list_accessible(conn, list_id, user["id"]):
            raise HTTPException(status_code=404, detail="List not found")
        try:
            await list_schema.create_list_field(
                conn, list_id, body.key, body.label, body.col_type, body.options, body.required)
        except ListSchemaError as e:
            raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True}


@router.patch("/{list_id:int}/fields/{key}")
async def patch_field(list_id: int, key: str, body: PatchFieldBody,
                      user: dict = Depends(get_current_user)) -> dict:
    pool = svc.get_pool()
    async with pool.acquire() as conn:
        if not await svc._list_accessible(conn, list_id, user["id"]):
            raise HTTPException(status_code=404, detail="List not found")
        try:
            await list_schema.update_list_field(
                conn, list_id, key, label=body.label, sort_order=body.sort_order,
                is_active=body.is_active, options=body.options)
        except ListSchemaError as e:
            raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True}


# ── Name-addressed compat shims (registered LAST — string catch-all) ──────────

@router.get("/{list_name}")
async def list_items_by_name(list_name: str, user: dict = Depends(get_current_user)) -> dict:
    return await svc.get_items(list_name, user_id=user["id"])


@router.post("/{list_name}/items")
async def add_by_name(list_name: str, body: AddItemsBody,
                      user: dict = Depends(get_current_user)) -> dict:
    # UI shim keeps create-on-add (explicit user action); items are plain strings here.
    texts = [i if isinstance(i, str) else i.get("text", "") for i in body.items]
    await svc.add_items(list_name, texts, user_id=user["id"])
    return await svc.get_items(list_name, user_id=user["id"])


@router.post("/{list_name}/clear")
async def clear_by_name(list_name: str, user: dict = Depends(get_current_user)) -> dict:
    await svc.clear_checked(list_name, user_id=user["id"])
    return await svc.get_items(list_name, user_id=user["id"])
