"""
Conversation API routes: CRUD, messages, branching, sharing.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.models.conversation import (
    ConversationCreate, ConversationUpdate, ConversationListItem,
    ConversationResponse, MessageResponse, SendMessageRequest,
)
from backend.middleware.auth import get_current_user, require_admin
from backend.database import get_pool

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


async def _check_conversation_access(conversation_id: int, user: dict) -> dict:
    """Verify user owns the conversation or has workspace access."""
    pool = get_pool()
    async with pool.acquire() as conn:
        conv = await conn.fetchrow(
            "SELECT * FROM public.bh_conversations WHERE id = $1", conversation_id
        )
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Owner or admin can access
        if conv["user_id"] == user["id"] or user["role"] == "admin":
            return dict(conv)

        # Check workspace membership (for shared conversations)
        member = await conn.fetchval("""
            SELECT 1 FROM public.bh_workspace_users
            WHERE workspace_id = $1 AND user_id = $2
        """, conv["workspace_id"], user["id"])

        if not member:
            raise HTTPException(status_code=403, detail="Access denied")
        return dict(conv)


@router.get("", response_model=List[ConversationListItem])
async def list_conversations(
    workspace_id: int = Query(...),
    include_archived: bool = Query(default=False),
    user: dict = Depends(get_current_user),
):
    """List conversations for a workspace, sorted by last activity."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Verify workspace access
        if user["role"] != "admin":
            access = await conn.fetchval("""
                SELECT 1 FROM public.bh_workspace_users
                WHERE workspace_id = $1 AND user_id = $2
            """, workspace_id, user["id"])
            if not access:
                raise HTTPException(status_code=403, detail="Access denied")

        query = """
            SELECT c.*,
                (SELECT COUNT(*) FROM bh_messages m WHERE m.conversation_id = c.id) as message_count
            FROM public.bh_conversations c
            WHERE c.workspace_id = $1 AND c.user_id = $2
        """
        params = [workspace_id, user["id"]]

        if not include_archived:
            query += " AND c.is_archived = false"

        query += " ORDER BY c.updated_at DESC LIMIT 100"

        rows = await conn.fetch(query, *params)

    return [
        ConversationListItem(
            id=r["id"], workspace_id=r["workspace_id"], title=r["title"],
            parent_id=r["parent_id"], is_archived=r["is_archived"],
            created_at=r["created_at"], updated_at=r["updated_at"],
            message_count=r["message_count"],
        )
        for r in rows
    ]


@router.post("", response_model=ConversationResponse)
async def create_conversation(body: ConversationCreate, user: dict = Depends(get_current_user)):
    """Create a new conversation in a workspace."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Verify workspace access
        if user["role"] != "admin":
            access = await conn.fetchval("""
                SELECT 1 FROM public.bh_workspace_users
                WHERE workspace_id = $1 AND user_id = $2
            """, body.workspace_id, user["id"])
            if not access:
                raise HTTPException(status_code=403, detail="Access denied to workspace")

        row = await conn.fetchrow("""
            INSERT INTO public.bh_conversations (workspace_id, user_id, title)
            VALUES ($1, $2, $3) RETURNING *
        """, body.workspace_id, user["id"], body.title)

    return ConversationResponse(
        id=row["id"], workspace_id=row["workspace_id"], user_id=row["user_id"],
        title=row["title"], parent_id=row["parent_id"],
        branch_point_msg=row["branch_point_msg"], is_archived=row["is_archived"],
        created_at=row["created_at"], updated_at=row["updated_at"], messages=[],
    )


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(conversation_id: int, user: dict = Depends(get_current_user)):
    """Get conversation with recent messages."""
    conv = await _check_conversation_access(conversation_id, user)
    pool = get_pool()
    async with pool.acquire() as conn:
        msg_rows = await conn.fetch("""
            SELECT * FROM public.bh_messages
            WHERE conversation_id = $1
            ORDER BY created_at DESC LIMIT 50
        """, conversation_id)

    messages = [
        MessageResponse(
            id=m["id"], conversation_id=m["conversation_id"], role=m["role"],
            content=m["content"], attachments=m["attachments"] or [],
            model_used=m["model_used"], routing_layer=m["routing_layer"],
            input_tokens=m["input_tokens"], output_tokens=m["output_tokens"],
            cost_usd=float(m["cost_usd"]) if m["cost_usd"] else None,
            metadata=m["metadata"] or {}, created_at=m["created_at"],
        )
        for m in reversed(msg_rows)  # Reverse to get chronological order
    ]

    return ConversationResponse(
        id=conv["id"], workspace_id=conv["workspace_id"], user_id=conv["user_id"],
        title=conv["title"], parent_id=conv["parent_id"],
        branch_point_msg=conv["branch_point_msg"], is_archived=conv["is_archived"],
        created_at=conv["created_at"], updated_at=conv["updated_at"],
        messages=messages,
    )


@router.get("/{conversation_id}/messages", response_model=List[MessageResponse])
async def get_messages(
    conversation_id: int,
    before: Optional[int] = Query(default=None, description="Load messages before this ID"),
    limit: int = Query(default=50, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """Get paginated messages for a conversation."""
    await _check_conversation_access(conversation_id, user)
    pool = get_pool()
    async with pool.acquire() as conn:
        if before:
            rows = await conn.fetch("""
                SELECT * FROM public.bh_messages
                WHERE conversation_id = $1 AND id < $2
                ORDER BY created_at DESC LIMIT $3
            """, conversation_id, before, limit)
        else:
            rows = await conn.fetch("""
                SELECT * FROM public.bh_messages
                WHERE conversation_id = $1
                ORDER BY created_at DESC LIMIT $2
            """, conversation_id, limit)

    return [
        MessageResponse(
            id=m["id"], conversation_id=m["conversation_id"], role=m["role"],
            content=m["content"], attachments=m["attachments"] or [],
            model_used=m["model_used"], routing_layer=m["routing_layer"],
            input_tokens=m["input_tokens"], output_tokens=m["output_tokens"],
            cost_usd=float(m["cost_usd"]) if m["cost_usd"] else None,
            metadata=m["metadata"] or {}, created_at=m["created_at"],
        )
        for m in reversed(rows)
    ]


@router.patch("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: int, body: ConversationUpdate, user: dict = Depends(get_current_user)
):
    """Rename or archive a conversation."""
    await _check_conversation_access(conversation_id, user)

    updates = []
    values = []
    idx = 1
    for field, value in body.model_dump(exclude_unset=True).items():
        updates.append(f"{field} = ${idx}")
        values.append(value)
        idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    values.append(conversation_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE public.bh_conversations SET {', '.join(updates)}, updated_at = now() WHERE id = ${idx} RETURNING *",
            *values,
        )

    return ConversationResponse(
        id=row["id"], workspace_id=row["workspace_id"], user_id=row["user_id"],
        title=row["title"], parent_id=row["parent_id"],
        branch_point_msg=row["branch_point_msg"], is_archived=row["is_archived"],
        created_at=row["created_at"], updated_at=row["updated_at"], messages=[],
    )


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: int, user: dict = Depends(require_admin)):
    """Permanently delete a conversation (admin only)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM public.bh_conversations WHERE id = $1", conversation_id)
    return {"ok": True}


@router.post("/{conversation_id}/branch/{msg_id}")
async def branch_conversation(conversation_id: int, msg_id: int, user: dict = Depends(get_current_user)):
    """Create a branch from a specific message in the conversation."""
    conv = await _check_conversation_access(conversation_id, user)
    pool = get_pool()
    async with pool.acquire() as conn:
        # Verify message exists in this conversation
        msg = await conn.fetchrow(
            "SELECT id FROM public.bh_messages WHERE id = $1 AND conversation_id = $2",
            msg_id, conversation_id,
        )
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found in this conversation")

        # Create branched conversation
        new_conv = await conn.fetchrow("""
            INSERT INTO public.bh_conversations
                (workspace_id, user_id, title, parent_id, branch_point_msg)
            VALUES ($1, $2, $3, $4, $5) RETURNING *
        """, conv["workspace_id"], user["id"],
            f"Branch of {conv['title'] or 'conversation'}", conversation_id, msg_id)

    return ConversationResponse(
        id=new_conv["id"], workspace_id=new_conv["workspace_id"], user_id=new_conv["user_id"],
        title=new_conv["title"], parent_id=new_conv["parent_id"],
        branch_point_msg=new_conv["branch_point_msg"], is_archived=new_conv["is_archived"],
        created_at=new_conv["created_at"], updated_at=new_conv["updated_at"], messages=[],
    )


@router.post("/{conversation_id}/share/{target_user_id}")
async def share_conversation(conversation_id: int, target_user_id: int, user: dict = Depends(get_current_user)):
    """Share a conversation with another user (read-only access via workspace membership)."""
    conv = await _check_conversation_access(conversation_id, user)

    # Verify target user has workspace access
    pool = get_pool()
    async with pool.acquire() as conn:
        access = await conn.fetchval("""
            SELECT 1 FROM public.bh_workspace_users
            WHERE workspace_id = $1 AND user_id = $2
        """, conv["workspace_id"], target_user_id)

        if not access:
            raise HTTPException(
                status_code=400,
                detail="Target user doesn't have access to this workspace"
            )

    return {"ok": True, "message": "Conversation shared (user has workspace access)"}
