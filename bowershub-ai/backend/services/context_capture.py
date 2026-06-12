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
        self.knowledge_root = config.KNOWLEDGE_ROOT

    async def evaluate(
        self, user_msg: str, assistant_msg: str, workspace_name: str
    ) -> List[CapturedFact]:
        """
        Evaluate a conversation exchange for capturable facts.
        Returns list of persisted facts (empty if nothing captured).
        """
        # Skip very short exchanges (unlikely to contain facts)
        if len(user_msg) < 20:
            return []

        try:
            result = await self.model_provider.complete(
                model=resolve_role("fast"),
                messages=[{"role": "user", "content": self.CAPTURE_PROMPT.format(
                    user_message=user_msg[:2000],
                    assistant_message=assistant_msg[:2000],
                )}],
                max_tokens=128,
            )

            facts = self._parse_facts(result.content)
            if not facts:
                return []

            persisted = []
            for fact in facts:
                topic = f"{workspace_name.lower()}/{fact.topic}"
                if not await self._is_duplicate(topic, fact.statement):
                    await self._persist(topic, fact.statement)
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

    async def _persist(self, topic: str, statement: str):
        """Append fact to /knowledge/<topic>.md"""
        file_path = self._get_knowledge_path(topic)

        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        date = datetime.now().strftime("%Y-%m-%d")
        line = f"- [{date}] {statement}\n"

        # Create file with header if new
        if not file_path.exists():
            header = f"# {topic.split('/')[-1].replace('-', ' ').title()}\n\n"
            file_path.write_text(header + line)
        else:
            with open(file_path, "a") as f:
                f.write(line)

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
