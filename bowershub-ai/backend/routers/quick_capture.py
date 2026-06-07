"""
Quick Capture router (`/api/quick-capture/*`).

Three thin endpoints that power the Quick_Capture overlay:

    POST /api/quick-capture/extract   — pass-through to smart-capture-extract
    POST /api/quick-capture/commit    — pass-through to smart-capture-commit
    POST /api/quick-capture/raw-note  — R9.9 fallback: write verbatim to
                                        /knowledge/captures/<slug>.md, never
                                        invoking the AI path

The first two delegate to the existing n8n smart-capture pipeline via
``backend.services.skill_executor``. Permission inheritance falls out of
``SkillExecutor.execute`` — the call runs in the user's current workspace
context, so the same per-workspace skill availability + per-user
restrictions that govern an in-chat ``smart-capture`` call govern the
overlay too. The router does not duplicate any of that logic.

The third endpoint is the explicit "AI-down" escape hatch (R9.9). It uses
``FileManager.append_knowledge`` so the resulting file lands inside the
existing knowledge base and is searchable by ``recall``.

Status code mapping:
    200  -> happy path
    400  -> request validation (missing fields, invalid token shape)
    403  -> permission/workspace check failed (SkillPermissionError)
    502  -> n8n / smart-capture upstream error (SkillExecutionError);
            response includes ``{retryable: true}`` so the overlay can
            offer Retry + Save-as-raw-note (R9.9 fallback path)

_Requirements: R9.2, R9.3, R9.4, R9.8, R9.9_
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.middleware.auth import get_current_user
from backend.services.file_manager import FileManager
from backend.services.skill_executor import (
    SkillExecutionError,
    SkillExecutor,
    SkillPermissionError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quick-capture", tags=["quick-capture"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ExtractRequest(BaseModel):
    """Body for POST /api/quick-capture/extract.

    At least one of ``text`` or ``image_path`` must be provided — that
    constraint is enforced explicitly in the handler so we can return
    a helpful 400 error message rather than Pydantic's generic shape.
    """

    text: Optional[str] = None
    image_path: Optional[str] = None
    workspace_id: int
    domain_hint: Optional[str] = None


class CommitRequest(BaseModel):
    """Body for POST /api/quick-capture/commit."""

    domain: str = Field(..., min_length=1)
    payload: dict[str, Any]
    asset_id: Optional[str] = None
    extract_token: str = Field(..., min_length=1)
    workspace_id: int


class RawNoteRequest(BaseModel):
    """Body for POST /api/quick-capture/raw-note (R9.9)."""

    text: str = Field(..., min_length=1)
    workspace_id: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, max_len: int = 50) -> str:
    """Produce a filesystem-safe slug from the first chunk of free-form text.

    Used for naming raw-note captures. Empty or non-alphanumeric input
    falls back to a UUID prefix so we never write to ``.md`` (which would
    collide on every empty save).
    """
    # Take the first line so a multi-paragraph note doesn't produce a
    # 500-char filename.
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    slug = _SLUG_RE.sub("-", first_line.lower()).strip("-")[:max_len]
    return slug or f"note-{uuid.uuid4().hex[:8]}"


def _raise_for_skill_error(exc: SkillExecutionError) -> None:
    """Translate ``SkillExecutionError`` to HTTP 502 with retry hint.

    R9.9: the overlay needs to know the failure is upstream/transient so
    it can offer Retry + Save-as-raw-note.
    """
    raise HTTPException(
        status_code=502,
        detail={
            "error": "smart_capture_unavailable",
            "skill": exc.skill_name,
            "upstream_status": exc.status_code or None,
            "message": exc.detail or str(exc),
            "retryable": True,
        },
    )


def _get_skill_executor(request: Request) -> SkillExecutor:
    """Build a ``SkillExecutor`` bound to the request's app config."""
    config = request.app.state.config
    return SkillExecutor(config)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/extract")
async def extract(
    body: ExtractRequest,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Pass-through to ``smart-capture-extract`` (R9.2, R9.3).

    Returns the upstream skill response unchanged so the overlay can
    show the extracted intents and the ``extract_token`` needed for the
    follow-up commit calls.
    """
    if not body.text and not body.image_path:
        raise HTTPException(
            status_code=400,
            detail="At least one of 'text' or 'image_path' must be provided",
        )

    params: dict[str, Any] = {}
    if body.text is not None:
        params["text"] = body.text
    if body.image_path is not None:
        params["image_path"] = body.image_path
    if body.domain_hint is not None:
        params["domain_hint"] = body.domain_hint

    executor = _get_skill_executor(request)

    try:
        result = await executor.execute(
            "smart-capture-extract",
            params,
            user_id=user["id"],
            workspace_id=body.workspace_id,
        )
    except SkillPermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except SkillExecutionError as e:
        logger.warning(
            "quick-capture extract failed: skill=%s status=%s detail=%s",
            e.skill_name, e.status_code, e.detail,
        )
        _raise_for_skill_error(e)

    raw = result.raw_data
    if isinstance(raw, dict):
        return raw
    # n8n really should always return JSON for smart-capture, but if it
    # doesn't we surface the body verbatim so the overlay can show
    # something useful instead of swallowing it.
    return {"ok": False, "raw": raw}


@router.post("/commit")
async def commit(
    body: CommitRequest,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Pass-through to ``smart-capture-commit`` (R9.4).

    The overlay calls this once per accepted intent. ``extract_token``
    is required by the upstream skill — we pass it through verbatim;
    the n8n workflow validates the timestamp signature (30-min expiry)
    so we don't duplicate that check here.
    """
    params: dict[str, Any] = {
        "domain": body.domain,
        "payload": body.payload,
        "extract_token": body.extract_token,
        "source": "quick-capture",
    }
    if body.asset_id is not None:
        params["asset_id"] = body.asset_id

    executor = _get_skill_executor(request)

    try:
        result = await executor.execute(
            "smart-capture-commit",
            params,
            user_id=user["id"],
            workspace_id=body.workspace_id,
        )
    except SkillPermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except SkillExecutionError as e:
        logger.warning(
            "quick-capture commit failed: skill=%s status=%s detail=%s",
            e.skill_name, e.status_code, e.detail,
        )
        _raise_for_skill_error(e)

    raw = result.raw_data
    if isinstance(raw, dict):
        return raw
    return {"ok": False, "raw": raw}


@router.post("/raw-note")
async def raw_note(
    body: RawNoteRequest,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Save freeform text verbatim to ``/knowledge/captures/<slug>.md``.

    R9.9 fallback path: bypasses the entire AI pipeline so users can
    capture even when n8n / smart-capture is down. The note is written
    with a small frontmatter-style header (date + source) followed by
    the raw body text, so it shows up in ``recall`` searches naturally.
    """
    config = request.app.state.config
    file_manager = FileManager(config)

    slug = _slugify(body.text)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    knowledge_root = Path(config.KNOWLEDGE_ROOT)
    captures_dir = knowledge_root / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)

    # Disambiguate when the same first-line slug is reused (e.g. multiple
    # captures starting with "TODO"). Keeps the filename predictable for
    # the first save while still being collision-safe for repeats.
    file_path = captures_dir / f"{slug}.md"
    if file_path.exists():
        suffix = uuid.uuid4().hex[:6]
        file_path = captures_dir / f"{slug}-{suffix}.md"
        slug = f"{slug}-{suffix}"

    # Use FileManager.append_knowledge for the actual write so any future
    # changes to knowledge-base I/O (locking, frontmatter, indexing) are
    # picked up here for free. The topic key is the path under
    # KNOWLEDGE_ROOT without the .md extension.
    topic = f"captures/{slug}"
    header_line = f"_Captured {timestamp} via Quick Capture (raw-note fallback)_"
    await file_manager.append_knowledge(topic, header_line)
    # Append the body text as-is, preserving the user's line breaks.
    await file_manager.append_knowledge(topic, "")
    for line in body.text.splitlines() or [body.text]:
        await file_manager.append_knowledge(topic, line)

    rel_path = f"captures/{slug}.md"
    return {
        "ok": True,
        "path": f"/knowledge/{rel_path}",
        "topic": topic,
    }
