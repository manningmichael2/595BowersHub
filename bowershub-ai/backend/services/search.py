"""
Search Service: full-text search across conversations, knowledge base, and artifacts.
Uses Postgres tsvector for messages/artifacts and file grep for knowledge.
"""

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from backend.config import Config
from backend.database import get_pool
from backend.services.file_manager import FileManager

logger = logging.getLogger(__name__)


class SearchResult:
    """A single search result."""
    def __init__(self, source_type: str, content: str, context: str = "",
                 workspace_id: Optional[int] = None, workspace_name: str = "",
                 conversation_id: Optional[int] = None, conversation_title: str = "",
                 message_id: Optional[int] = None, relevance: float = 0.0):
        self.source_type = source_type
        self.content = content
        self.context = context
        self.workspace_id = workspace_id
        self.workspace_name = workspace_name
        self.conversation_id = conversation_id
        self.conversation_title = conversation_title
        self.message_id = message_id
        self.relevance = relevance

    def dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type,
            "content": self.content,
            "context": self.context,
            "workspace_id": self.workspace_id,
            "workspace_name": self.workspace_name,
            "conversation_id": self.conversation_id,
            "conversation_title": self.conversation_title,
            "message_id": self.message_id,
            "relevance": self.relevance,
        }


class SearchService:
    """Searches across all content types with permission scoping."""

    def __init__(self, config: Config):
        self.config = config
        self.file_manager = FileManager(config)

    async def search(
        self,
        query: str,
        user_id: int,
        workspace_id: Optional[int] = None,
        content_type: str = "all",  # 'all', 'messages', 'knowledge', 'artifacts'
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        limit: int = 30,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Search across all content types.
        Returns results grouped by source type.
        """
        results: Dict[str, List[Dict[str, Any]]] = {
            "messages": [],
            "knowledge": [],
            "artifacts": [],
        }

        # Get user's accessible workspace IDs
        accessible_workspaces = await self._get_accessible_workspaces(user_id)
        if workspace_id and workspace_id not in accessible_workspaces:
            return results  # No access

        target_workspaces = [workspace_id] if workspace_id else accessible_workspaces

        if content_type in ("all", "messages"):
            results["messages"] = await self._search_messages(
                query, target_workspaces, date_from, date_to, limit
            )

        if content_type in ("all", "knowledge"):
            results["knowledge"] = await self._search_knowledge(query, limit)

        if content_type in ("all", "artifacts"):
            results["artifacts"] = await self._search_artifacts(
                query, target_workspaces, limit
            )

        return results

    async def _get_accessible_workspaces(self, user_id: int) -> List[int]:
        """Get workspace IDs the user can access."""
        pool = get_pool()
        async with pool.acquire() as conn:
            # Check if admin
            user = await conn.fetchrow(
                "SELECT role FROM public.bh_users WHERE id = $1", user_id
            )
            if user and user["role"] == "admin":
                rows = await conn.fetch("SELECT id FROM public.bh_workspaces")
            else:
                rows = await conn.fetch("""
                    SELECT workspace_id as id FROM public.bh_workspace_users
                    WHERE user_id = $1
                """, user_id)
        return [r["id"] for r in rows]

    async def _search_messages(
        self, query: str, workspace_ids: List[int],
        date_from: Optional[date], date_to: Optional[date], limit: int
    ) -> List[Dict[str, Any]]:
        """Full-text search on messages using Postgres tsvector."""
        pool = get_pool()
        async with pool.acquire() as conn:
            sql = """
                SELECT m.id, m.content, m.role, m.created_at, m.conversation_id,
                       c.title as conversation_title, c.workspace_id,
                       w.name as workspace_name,
                       ts_rank(to_tsvector('english', m.content), plainto_tsquery('english', $1)) as rank
                FROM public.bh_messages m
                JOIN public.bh_conversations c ON c.id = m.conversation_id
                JOIN public.bh_workspaces w ON w.id = c.workspace_id
                WHERE to_tsvector('english', m.content) @@ plainto_tsquery('english', $1)
                AND c.workspace_id = ANY($2)
            """
            params: List[Any] = [query, workspace_ids]
            idx = 3

            if date_from:
                sql += f" AND m.created_at >= ${idx}"
                params.append(date_from)
                idx += 1
            if date_to:
                sql += f" AND m.created_at <= ${idx}"
                params.append(date_to)
                idx += 1

            sql += f" ORDER BY rank DESC LIMIT ${idx}"
            params.append(limit)

            rows = await conn.fetch(sql, *params)

        results = []
        for r in rows:
            # Get surrounding context (1 message before and after)
            context = await self._get_message_context(r["conversation_id"], r["id"])
            results.append({
                "source_type": "message",
                "content": r["content"][:500],
                "context": context,
                "workspace_id": r["workspace_id"],
                "workspace_name": r["workspace_name"],
                "conversation_id": r["conversation_id"],
                "conversation_title": r["conversation_title"] or "Untitled",
                "message_id": r["id"],
                "role": r["role"],
                "created_at": r["created_at"].isoformat(),
                "relevance": float(r["rank"]),
            })
        return results

    async def _get_message_context(self, conversation_id: int, message_id: int) -> str:
        """Get 1 message before and after for context."""
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                (SELECT content, role FROM public.bh_messages
                 WHERE conversation_id = $1 AND id < $2 ORDER BY id DESC LIMIT 1)
                UNION ALL
                (SELECT content, role FROM public.bh_messages
                 WHERE conversation_id = $1 AND id > $2 ORDER BY id ASC LIMIT 1)
            """, conversation_id, message_id)

        parts = []
        for r in rows:
            prefix = "User" if r["role"] == "user" else "AI"
            parts.append(f"{prefix}: {r['content'][:200]}")
        return " | ".join(parts)

    async def _search_knowledge(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Search knowledge base markdown files."""
        matches = await self.file_manager.search_knowledge(query)
        return [
            {
                "source_type": "knowledge",
                "content": m["match"],
                "context": "",
                "file": m["file"],
                "topic": m["topic"],
            }
            for m in matches[:limit]
        ]

    async def _search_artifacts(
        self, query: str, workspace_ids: List[int], limit: int
    ) -> List[Dict[str, Any]]:
        """Full-text search on artifacts."""
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT a.id, a.title, a.content, a.artifact_type, a.created_at,
                       c.workspace_id, w.name as workspace_name
                FROM public.bh_artifacts a
                JOIN public.bh_conversations c ON c.id = a.conversation_id
                JOIN public.bh_workspaces w ON w.id = c.workspace_id
                WHERE to_tsvector('english', a.content) @@ plainto_tsquery('english', $1)
                AND c.workspace_id = ANY($2)
                ORDER BY a.created_at DESC
                LIMIT $3
            """, query, workspace_ids, limit)

        return [
            {
                "source_type": "artifact",
                "content": r["content"][:300],
                "title": r["title"],
                "artifact_type": r["artifact_type"],
                "workspace_id": r["workspace_id"],
                "workspace_name": r["workspace_name"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
