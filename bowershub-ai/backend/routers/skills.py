"""
Skill API routes: CRUD for admin, list for users, test endpoint.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.middleware.auth import get_current_user, require_admin
from backend.database import get_pool
from backend.services.skill_executor import SkillExecutor
from backend.config import Config

router = APIRouter(prefix="/api/skills", tags=["skills"])


class SkillCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1)
    webhook_url: str = Field(..., min_length=1)
    http_method: str = Field(default="POST", pattern="^(GET|POST|PUT|PATCH|DELETE)$")
    param_schema: dict = {}
    response_hint: Optional[str] = None
    restricted_users: List[int] = []
    min_role: Optional[str] = Field(default=None, pattern="^(member|admin)$")


class SkillUpdate(BaseModel):
    description: Optional[str] = None
    webhook_url: Optional[str] = None
    http_method: Optional[str] = None
    param_schema: Optional[dict] = None
    response_hint: Optional[str] = None
    is_active: Optional[bool] = None
    restricted_users: Optional[List[int]] = None
    min_role: Optional[str] = Field(default=None, pattern="^(member|admin)$")


class SkillResponse(BaseModel):
    id: int
    name: str
    description: str
    webhook_url: str
    http_method: str
    param_schema: dict
    response_hint: Optional[str]
    is_active: bool
    restricted_users: List[int]
    min_role: Optional[str] = None


class SkillTestRequest(BaseModel):
    params: dict = {}


@router.get("", response_model=List[SkillResponse])
async def list_skills(user: dict = Depends(get_current_user)):
    """List skills. Admins see all; members see only permitted skills."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if user["role"] == "admin":
            rows = await conn.fetch("SELECT * FROM public.bh_skills ORDER BY name")
        else:
            # Show skills available in user's workspaces
            rows = await conn.fetch("""
                SELECT DISTINCT s.* FROM public.bh_skills s
                JOIN public.bh_workspace_skills ws ON ws.skill_id = s.id
                JOIN public.bh_workspace_users wu ON wu.workspace_id = ws.workspace_id
                WHERE wu.user_id = $1 AND s.is_active = true
                ORDER BY s.name
            """, user["id"])

    return [
        SkillResponse(
            id=r["id"], name=r["name"], description=r["description"],
            webhook_url=r["webhook_url"], http_method=r["http_method"],
            param_schema=r["param_schema"] if isinstance(r["param_schema"], dict) else {},
            response_hint=r["response_hint"],
            is_active=r["is_active"],
            restricted_users=list(r["restricted_users"]) if r["restricted_users"] else [],
            min_role=r["min_role"],
        )
        for r in rows
    ]


@router.post("", response_model=SkillResponse)
async def create_skill(body: SkillCreate, user: dict = Depends(require_admin)):
    """Create a new skill (admin only)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO public.bh_skills
                (name, description, webhook_url, http_method, param_schema, response_hint, restricted_users, min_role)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING *
        """, body.name, body.description, body.webhook_url, body.http_method,
            body.param_schema, body.response_hint, body.restricted_users, body.min_role)

    return SkillResponse(
        id=row["id"], name=row["name"], description=row["description"],
        webhook_url=row["webhook_url"], http_method=row["http_method"],
        param_schema=row["param_schema"] if isinstance(row["param_schema"], dict) else {},
        response_hint=row["response_hint"],
        is_active=row["is_active"],
        restricted_users=list(row["restricted_users"]) if row["restricted_users"] else [],
        min_role=row["min_role"],
    )


@router.patch("/{skill_id}", response_model=SkillResponse)
async def update_skill(skill_id: int, body: SkillUpdate, user: dict = Depends(require_admin)):
    """Update a skill (admin only)."""
    updates = []
    values = []
    idx = 1
    for field, value in body.model_dump(exclude_unset=True).items():
        updates.append(f"{field} = ${idx}")
        values.append(value)
        idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    values.append(skill_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE public.bh_skills SET {', '.join(updates)} WHERE id = ${idx} RETURNING *",
            *values,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Skill not found")

    return SkillResponse(
        id=row["id"], name=row["name"], description=row["description"],
        webhook_url=row["webhook_url"], http_method=row["http_method"],
        param_schema=row["param_schema"] or {}, response_hint=row["response_hint"],
        is_active=row["is_active"], restricted_users=row["restricted_users"] or [],
        min_role=row["min_role"],
    )


@router.delete("/{skill_id}")
async def delete_skill(skill_id: int, user: dict = Depends(require_admin)):
    """Delete a skill (admin only)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM public.bh_skills WHERE id = $1", skill_id)
    return {"ok": True}


from backend.http_client import get_http_session


@router.post("/{skill_id}/test")
async def test_skill(skill_id: int, body: SkillTestRequest, request=None, user: dict = Depends(require_admin)):
    """Test a skill with sample input (admin only)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        skill = await conn.fetchrow("SELECT * FROM public.bh_skills WHERE id = $1", skill_id)

    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    from fastapi import Request
    config = Config()  # Will be replaced with app.state.config in real usage
    executor = SkillExecutor(config)

    try:
        # Direct execution without permission checks (admin testing)
        url = skill["webhook_url"]
        if url.startswith("/"):
            url = f"{executor.n8n_base}{url}"

        async with get_http_session() as client:
            if skill["http_method"].upper() == "GET":
                response = await client.get(url, params=body.params, timeout=httpx.Timeout(5.0, read=30.0))
            else:
                response = await client.post(url, json=body.params, timeout=httpx.Timeout(5.0, read=30.0))

        return {
            "status_code": response.status_code,
            "response": response.json() if "application/json" in response.headers.get("content-type", "") else response.text[:2000],
        }
    except Exception as e:
        return {"error": str(e)}
