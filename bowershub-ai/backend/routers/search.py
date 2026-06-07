"""
Search API route: global search across messages, knowledge, and artifacts.
"""

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request

from backend.middleware.auth import get_current_user
from backend.services.search import SearchService

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
async def search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=200),
    workspace: Optional[int] = Query(default=None),
    type: str = Query(default="all", pattern="^(all|messages|knowledge|artifacts)$"),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """
    Global search across conversations, knowledge base, and artifacts.
    Results are scoped to the user's accessible workspaces.
    """
    config = request.app.state.config
    search_service = SearchService(config)

    results = await search_service.search(
        query=q,
        user_id=user["id"],
        workspace_id=workspace,
        content_type=type,
        date_from=date_from,
        date_to=date_to,
    )

    # Count totals
    total = sum(len(v) for v in results.values())

    return {
        "query": q,
        "total_results": total,
        "results": results,
    }
