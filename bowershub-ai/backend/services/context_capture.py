"""
Automated Context Capture: scans conversations post-message and
silently persists important facts, decisions, and preferences.
"""

import json
from backend.services.model_catalog import resolve_role
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from backend.config import Config
from backend.services.model_provider import ModelProvider

logger = logging.getLogger(__name__)


class CapturedFact:
    """A fact extracted from conversation."""
    def __init__(self, topic: str, statement: str):
        self.topic = topic
        self.statement = statement


class ContextCapture:
    """
    Runs as a background task after each assistant response.
    Evaluates whether the exchange contains persistable information.
    """

    CAPTURE_PROMPT = """Analyze this conversation exchange. Extract any facts, preferences, decisions, or corrections the user explicitly stated that would be useful to remember long-term.

Rules:
- Only extract EXPLICIT statements by the user, never infer or assume
- Format each fact as a single clear sentence
- Return JSON only: {{"facts": [{{"topic": "...", "statement": "..."}}]}} or {{"facts": []}} if nothing to capture
- Topics should be lowercase slugs matching the domain: "accounts", "tools", "preferences", "people"
- Do NOT capture: questions, hypotheticals, things the AI said, or general knowledge

Exchange:
User: {user_message}
Assistant: {assistant_message}"""

    def __init__(self, model_provider: ModelProvider, config: Config):
        self.model_provider = model_provider
        self.config = config
        self.knowledge_root = config.KNOWLEDGE_ROOT

    async def evaluate(
        self, user_msg: str, assistant_msg: str, workspace_name: str,
        captured_by: Optional[str] = None, user_id: Optional[int] = None,
    ) -> List[CapturedFact]:
        """
        Evaluate a conversation exchange for capturable facts.
        Returns list of persisted facts (empty if nothing captured).

        captured_by: the display name of the user whose exchange this was, so the
        stored fact records *from whom* it was captured (household attribution).
        None for system/automated runs with no associated user.
        user_id: the capturing user's id, recorded as the entity's created_by when
        the fact is mirrored into the pgvector knowledge graph.
        """
        # Skip very short exchanges (unlikely to contain facts)
        if len(user_msg) < 20:
            return []

        try:
            content = await self._run_extraction(self.CAPTURE_PROMPT.format(
                user_message=user_msg[:2000],
                assistant_message=assistant_msg[:2000],
            ))
            facts = self._parse_facts(content)
            if not facts:
                return []

            persisted = []
            for fact in facts:
                topic = f"{workspace_name.lower()}/{fact.topic}"
                if not await self._is_duplicate(topic, fact.statement):
                    await self._persist(topic, fact.statement, captured_by)
                    # Also mirror into the pgvector knowledge graph so the fact is
                    # semantically searchable (feeds hybrid_retrieval) — the same
                    # entity store the manual /remember writes to. Non-critical: a
                    # graph write failure must never lose the markdown capture.
                    await self._persist_entity(fact, captured_by, user_id)
                    persisted.append(fact)

            if persisted:
                logger.info(f"Context captured: {len(persisted)} fact(s) in {workspace_name}")

            return persisted

        except Exception as e:
            logger.warning(f"Context capture failed (non-blocking): {e}")
            return []

    def _parse_facts(self, content: str) -> List[CapturedFact]:
        """Parse the AI response into CapturedFact objects."""
        try:
            # Handle potential markdown wrapping
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            data = json.loads(content)
            facts = []
            for item in data.get("facts", []):
                if item.get("topic") and item.get("statement"):
                    facts.append(CapturedFact(
                        topic=item["topic"].strip().lower().replace(" ", "-"),
                        statement=item["statement"].strip(),
                    ))
            return facts
        except (json.JSONDecodeError, KeyError, TypeError):
            return []

    async def _is_duplicate(self, topic: str, statement: str) -> bool:
        """Check if this fact already exists in the knowledge file."""
        file_path = self._get_knowledge_path(topic)
        if not file_path.exists():
            return False

        existing = file_path.read_text()
        # Simple substring check (fast path)
        if statement.lower() in existing.lower():
            return True

        return False

    async def _persist(self, topic: str, statement: str,
                       captured_by: Optional[str] = None):
        """Append fact to /knowledge/<topic>.md, recording the capturing user."""
        file_path = self._get_knowledge_path(topic)

        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        date = datetime.now().strftime("%Y-%m-%d")
        # Stamp the author when known so a shared household knows from whom a fact
        # came; statement stays intact so the _is_duplicate substring check holds.
        who = f" ({captured_by})" if captured_by else ""
        line = f"- [{date}]{who} {statement}\n"

        # Create file with header if new
        if not file_path.exists():
            header = f"# {topic.split('/')[-1].replace('-', ' ').title()}\n\n"
            file_path.write_text(header + line)
        else:
            with open(file_path, "a") as f:
                f.write(line)

    # Map a captured fact's topic slug → knowledge-graph entity_type. Mirrors the
    # manual /remember mapping (skills/knowledge.py) so auto- and hand-captured
    # facts are typed consistently. Unknown topics fall back to 'note'.
    _ENTITY_TYPE_MAP = {
        "preferences": "preference", "preference": "preference",
        "people": "person", "person": "person",
        "accounts": "account", "tools": "tool",
        "finance": "fact", "house": "fact", "household": "fact",
    }

    async def _run_extraction(self, prompt: str) -> str:
        """Run the fact-extraction LLM call against local Ollama and return the raw
        response text. Deliberately a DIRECT call (not the shared model_provider):
        capture is a background task with needs the hot-path provider doesn't serve
        — `think:false` (qwen3 reasoning wastes the budget + time), strict JSON
        output, and a generous timeout (the provider hard-caps Ollama calls at 15s,
        too short for an 8B model). Free + private: never leaves the box."""
        from backend.http_client import get_http_client
        model = await self._capture_model()
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"num_predict": 256},
        }
        url = self.config.OLLAMA_URL.rstrip("/") + "/api/chat"
        resp = await get_http_client().post(url, json=body, timeout=90.0)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")

    async def _capture_model(self) -> str:
        """The model used for fact extraction. DB-configurable via the
        'context_capture.model' platform setting (NO-HARDCODING); falls back to
        the 'local' role alias so it stays on-box/private if the setting is unset
        or the DB is unreachable (e.g. unit tests)."""
        try:
            from backend.database import get_pool
            pool = get_pool()
            async with pool.acquire() as conn:
                m = await conn.fetchval(
                    "SELECT value_json->>'model' FROM public.bh_platform_settings "
                    "WHERE key = 'context_capture.model'")
            if m:
                return m
        except Exception:
            pass
        return resolve_role("local")

    async def _persist_entity(self, fact: "CapturedFact",
                              captured_by: Optional[str], user_id: Optional[int]):
        """Mirror a captured fact into the pgvector knowledge graph as an entity so
        it's hybrid-retrievable. Each fact is its own entity (name = statement) so
        distinct facts don't collapse; remember_entity dedups exact repeats by name.
        Failure is swallowed — the markdown capture is the source of truth."""
        try:
            from backend.services.knowledge_graph import remember_entity
            entity_type = self._ENTITY_TYPE_MAP.get(fact.topic, "note")
            # Name = a concise, stable handle for the fact (its statement, capped).
            name = fact.statement.strip()[:120]
            await remember_entity(
                name=name,
                entity_type=entity_type,
                summary=fact.statement,
                attributes={"topic": fact.topic, "captured_by": captured_by,
                            "auto_captured": True},
                source="context_capture",
                user_id=user_id,
            )
        except Exception as e:
            logger.warning(f"Context capture: graph mirror failed (non-blocking): {e}")

    def _get_knowledge_path(self, topic: str) -> Path:
        """Get the file path for a knowledge topic."""
        # Sanitize topic to prevent path traversal
        safe_topic = topic.replace("..", "").strip("/")
        return Path(self.knowledge_root) / f"{safe_topic}.md"

    async def get_workspace_context(self, workspace_name: str) -> str:
        """Get all captured context for a workspace as a readable summary."""
        workspace_dir = Path(self.knowledge_root) / workspace_name.lower()
        if not workspace_dir.exists():
            return "No captured context for this workspace yet."

        lines = [f"**Captured context for {workspace_name}:**\n"]
        for md_file in sorted(workspace_dir.glob("*.md")):
            topic = md_file.stem.replace("-", " ").title()
            content = md_file.read_text()
            # Extract just the facts (lines starting with "- [")
            facts = [l.strip() for l in content.split("\n") if l.strip().startswith("- [")]
            if facts:
                lines.append(f"\n**{topic}:**")
                lines.extend(facts[-10:])  # Last 10 facts per topic
                if len(facts) > 10:
                    lines.append(f"  *...and {len(facts) - 10} more*")

        return "\n".join(lines) if len(lines) > 1 else "No captured context for this workspace yet."

    async def delete_fact(self, workspace_name: str, topic: str, statement: str) -> bool:
        """Delete a specific fact from the knowledge base."""
        file_path = self._get_knowledge_path(f"{workspace_name.lower()}/{topic}")
        if not file_path.exists():
            return False

        lines = file_path.read_text().split("\n")
        new_lines = [l for l in lines if statement not in l]

        if len(new_lines) == len(lines):
            return False  # Fact not found

        file_path.write_text("\n".join(new_lines))
        return True
