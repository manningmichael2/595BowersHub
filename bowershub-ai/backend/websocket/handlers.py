"""
WebSocket endpoint handler: authentication, message dispatch, streaming.
"""

import asyncio
import json
import logging
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from backend.websocket.manager import WebSocketManager
from backend.services.auth import AuthService
from backend.database import get_pool
from backend.config import Config

logger = logging.getLogger(__name__)


# In-flight routing tasks keyed by (user_id, conversation_id) so a "cancel"
# message can stop a still-running response. Single-process is fine for now —
# revisit if/when we add horizontal scaling.
_active_tasks: dict[tuple[int, int], asyncio.Task] = {}


async def websocket_chat_handler(
    websocket: WebSocket,
    ws_manager: WebSocketManager,
    config: Config,
    model_provider=None,
):
    """
    Main WebSocket handler for /ws/chat.

    Protocol:
    1. Client connects
    2. Client sends auth message: {"type": "auth", "token": "<jwt>"}
    3. Server validates JWT, registers connection
    4. Client sends messages: {"type": "message", "conversation_id": N, "content": "...", "model": "auto", "attachments": []}
    5. Server streams responses: typing → tokens → skill_status → complete
    """
    # Accept connection (we'll validate auth in the first message)
    await websocket.accept()

    user_id: Optional[int] = None
    user: Optional[dict] = None

    try:
        # Wait for auth message (first message must be auth)
        auth_data = await websocket.receive_json()

        if auth_data.get("type") != "auth" or "token" not in auth_data:
            await websocket.send_json({
                "type": "error",
                "data": {"message": "First message must be: {\"type\": \"auth\", \"token\": \"<jwt>\"}"}
            })
            await websocket.close(code=4001, reason="Auth required")
            return

        # Validate JWT
        pool = get_pool()
        auth_service = AuthService(pool, config)
        payload = auth_service.validate_access_token(auth_data["token"])

        if not payload:
            await websocket.send_json({
                "type": "error",
                "data": {"message": "Invalid or expired token"}
            })
            await websocket.close(code=4001, reason="Invalid token")
            return

        user_id = payload["user_id"]
        user = await auth_service.get_user_by_id(user_id)

        if not user or not user["is_active"]:
            await websocket.send_json({
                "type": "error",
                "data": {"message": "User not found or deactivated"}
            })
            await websocket.close(code=4001, reason="User invalid")
            return

        # Register connection (re-accept not needed since we already accepted above)
        # We need to track it manually since we already accepted
        ws_manager.connections.setdefault(user_id, []).append(websocket)
        logger.info(f"WebSocket authenticated: user={user_id} ({user['email']})")

        # Send auth success
        await websocket.send_json({
            "type": "auth_success",
            "data": {"user_id": user_id, "email": user["email"]}
        })

        # Message loop
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "message":
                # Re-load the live user (role + is_active) per message before
                # dispatch — the connect-time snapshot (line ~74) is captured once
                # and must never be trusted for authorization. A demotion or
                # deactivation thus takes effect on the NEXT message with no
                # reconnect (R1.6/R1.7); skill_executor also re-fetches role per
                # skill, but other role-dependent logic in handle_chat_message
                # would otherwise read the stale role.
                user = await auth_service.get_user_by_id(user_id)
                if not user or not user["is_active"]:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": "User not found or deactivated"},
                    })
                    await websocket.close(code=4001, reason="User invalid")
                    return
                conversation_id = data.get("conversation_id")
                key = (user_id, conversation_id) if conversation_id else None
                # If a previous response is still running for this conversation,
                # cancel it so we don't end up with overlapping responses.
                if key and key in _active_tasks:
                    old = _active_tasks.pop(key)
                    if not old.done():
                        old.cancel()
                task = asyncio.create_task(handle_chat_message(
                    data=data,
                    user=user,
                    websocket=websocket,
                    ws_manager=ws_manager,
                    config=config,
                    model_provider=model_provider,
                ))
                if key:
                    _active_tasks[key] = task
                    task.add_done_callback(lambda t, k=key: _active_tasks.pop(k, None))
            elif msg_type == "cancel":
                conversation_id = data.get("conversation_id")
                key = (user_id, conversation_id) if conversation_id else None
                task = _active_tasks.get(key) if key else None
                if task and not task.done():
                    task.cancel()
                    await websocket.send_json({
                        "type": "cancelled",
                        "conversation_id": conversation_id,
                        "data": {"message": "Response cancelled."},
                    })
                else:
                    await websocket.send_json({
                        "type": "cancelled",
                        "conversation_id": conversation_id,
                        "data": {"message": "Nothing in progress to cancel."},
                    })
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": f"Unknown message type: {msg_type}"}
                })

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: user={user_id}")
    except json.JSONDecodeError:
        logger.warning(f"WebSocket received invalid JSON from user={user_id}")
        try:
            await websocket.send_json({
                "type": "error",
                "data": {"message": "Invalid JSON"}
            })
        except Exception:
            pass
    except Exception as e:
        logger.error(f"WebSocket error for user={user_id}: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "data": {"message": "Internal server error"}
            })
        except Exception:
            pass
    finally:
        if user_id is not None:
            ws_manager.disconnect(websocket, user_id)


async def handle_chat_message(
    data: dict,
    user: dict,
    websocket: WebSocket,
    ws_manager: WebSocketManager,
    config: Config,
    model_provider=None,
):
    """
    Handle an incoming chat message from the WebSocket.
    Dispatches to the router engine for processing.

    Expected data format:
    {
        "type": "message",
        "conversation_id": 123,
        "content": "what's my balance?",
        "model": "auto",
        "attachments": []
    }
    """
    conversation_id = data.get("conversation_id")
    content = data.get("content", "").strip()
    model = data.get("model", "auto")
    attachments = data.get("attachments", [])
    # Chat-bar Personal/Shared toggle: visibility the Context Harvester applies to
    # facts captured from this message. Default 'private' (Personal) — auto-capture
    # never silently shares. Untrusted client input, so clamp to the known values.
    capture_visibility = data.get("capture_visibility", "private")
    if capture_visibility not in ("private", "shared"):
        capture_visibility = "private"

    if not content:
        await websocket.send_json({
            "type": "error",
            "conversation_id": conversation_id,
            "data": {"message": "Message content cannot be empty"}
        })
        return

    if len(content) > 10000:
        await websocket.send_json({
            "type": "error",
            "conversation_id": conversation_id,
            "data": {"message": "Message too long (max 10,000 characters)"}
        })
        return

    # Send typing indicator
    await ws_manager.send_typing(user["id"], conversation_id)

    pool = get_pool()

    # Load workspace context for routing
    async with pool.acquire() as conn:
        conv = await conn.fetchrow(
            "SELECT * FROM public.bh_conversations WHERE id = $1", conversation_id
        )
        if not conv:
            await ws_manager.send_error(user["id"], conversation_id, "Conversation not found")
            return

        workspace = await conn.fetchrow(
            "SELECT * FROM public.bh_workspaces WHERE id = $1", conv["workspace_id"]
        )
        if not workspace:
            await ws_manager.send_error(user["id"], conversation_id, "Workspace not found")
            return

    # Save user message to DB
    async with pool.acquire() as conn:
        user_msg = await conn.fetchrow("""
            INSERT INTO public.bh_messages (conversation_id, role, content, attachments)
            VALUES ($1, 'user', $2, $3::jsonb)
            RETURNING id, created_at
        """, conversation_id, content, json.dumps(attachments))

        # Update conversation timestamp
        await conn.execute(
            "UPDATE public.bh_conversations SET updated_at = now() WHERE id = $1",
            conversation_id,
        )

    # Build routing context
    from backend.services.router_engine import RouterEngine, RoutingContext
    from backend.services.skill_executor import SkillExecutor
    from backend.services.model_provider import ModelProvider

    # Use shared model_provider if passed; otherwise create one
    if model_provider is None:
        model_provider = ModelProvider(config)
    skill_executor = SkillExecutor(config)
    router = RouterEngine(model_provider, skill_executor, config)

    routing_context = RoutingContext(
        user_id=user["id"],
        # Prompt-flavor only — NO authz decision may read user_role. Skill gating
        # re-fetches the live role in skill_executor; this carries the role into
        # the prompt context, nothing more (R1.6).
        user_role=user["role"],
        workspace_id=workspace["id"],
        workspace_name=workspace["name"],
        system_prompt=workspace["system_prompt"],
        default_model=workspace["default_model"],
        max_context_tokens=workspace["max_context_tokens"],
        permitted_schemas=workspace["permitted_schemas"] or [],
        conversation_id=conversation_id,
        force_model=model if model != "auto" else None,
        attachments=attachments,
    )

    # Route the message
    try:
        result = await router.route(content, routing_context, ws_manager)
    except asyncio.CancelledError:
        logger.info(f"Routing cancelled by user: user={user['id']} conv={conversation_id}")
        # Persist a placeholder so the conversation history reflects the cancel.
        # Wrap in shield so the cancellation doesn't kill the INSERT/notify too.
        async def _persist_and_notify():
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO public.bh_messages
                        (conversation_id, role, content, metadata)
                    VALUES ($1, 'assistant', $2, $3::jsonb)
                """, conversation_id, "_(response cancelled)_", json.dumps({"cancelled": True}))
            await ws_manager.send_cancelled(user["id"], conversation_id)
        try:
            await asyncio.shield(_persist_and_notify())
        except Exception as e:
            logger.warning(f"Failed to persist cancellation marker: {e}")
        raise
    except Exception as e:
        logger.error(f"Router error: {e}", exc_info=True)
        await ws_manager.send_error(user["id"], conversation_id, "Something went wrong. Try again?")
        return

    # Save assistant message to DB
    async with pool.acquire() as conn:
        assistant_msg = await conn.fetchrow("""
            INSERT INTO public.bh_messages
                (conversation_id, role, content, model_used, routing_layer,
                 input_tokens, output_tokens, cost_usd, metadata)
            VALUES ($1, 'assistant', $2, $3, $4, $5, $6, $7, $8::jsonb)
            RETURNING id, created_at
        """, conversation_id, result.content, result.model_used, result.layer,
            result.input_tokens, result.output_tokens, result.cost_usd,
            json.dumps({"skill_name": result.skill_name} if result.skill_name else {}))

    # Send complete message to client
    await ws_manager.send_complete(user["id"], conversation_id, {
        "id": assistant_msg["id"],
        "content": result.content,
        "role": "assistant",
        "model_used": result.model_used,
        "routing_layer": result.layer,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost_usd": result.cost_usd,
        "metadata": {"skill_name": result.skill_name} if result.skill_name else {},
        "created_at": assistant_msg["created_at"].isoformat(),
    })

    # Fire message_received hooks (proactive context capture, etc.). The user
    # already has their reply above, so this runs AFTER the response and never
    # affects latency; dispatch() itself spawns each hook as a background task.
    hook_engine = getattr(getattr(websocket, "app", None), "state", None)
    hook_engine = getattr(hook_engine, "hook_engine", None)
    if hook_engine is not None:
        from backend.services.hook_engine import HookEventContext
        try:
            await hook_engine.dispatch("message_received", HookEventContext(
                workspace_id=workspace["id"],
                user_id=user["id"],
                conversation_id=conversation_id,
                user_message=content,
                assistant_message=result.content,
                skill_name=result.skill_name,
                capture_visibility=capture_visibility,
            ))
        except Exception as e:
            logger.debug(f"message_received hook dispatch failed (non-blocking): {e}")
