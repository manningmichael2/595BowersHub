"""
Artifact Manager: detects, stores, and versions rich output content
(code, HTML, diagrams, charts, tables) from AI responses.
"""

import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.config import Config
from backend.database import get_pool

logger = logging.getLogger(__name__)


class DetectedArtifact:
    """An artifact detected in AI response content."""
    def __init__(self, artifact_type: str, content: str, title: str = "",
                 language: Optional[str] = None, span: Tuple[int, int] = (0, 0)):
        self.artifact_type = artifact_type
        self.content = content
        self.title = title
        self.language = language
        self.span = span


class ArtifactManager:
    """Detects, stores, and manages artifacts from AI responses."""

    # Detection rules: pattern, min_lines/condition, artifact_type
    CODE_PATTERN = re.compile(r'```(\w+)?\n(.*?)```', re.DOTALL)
    HTML_PATTERN = re.compile(r'```html?\n(.*?)```', re.DOTALL)
    MERMAID_PATTERN = re.compile(r'```mermaid\n(.*?)```', re.DOTALL)
    TABLE_PATTERN = re.compile(r'(\|[^\n]+\|\n\|[-: |]+\|\n(?:\|[^\n]+\|\n){8,})', re.MULTILINE)

    MIN_CODE_LINES = 15
    MIN_TABLE_ROWS = 10

    def __init__(self, config: Config):
        self.config = config
        self.files_root = Path(config.FILES_ROOT)

    def detect(self, content: str) -> List[DetectedArtifact]:
        """Detect artifact-worthy content in an AI response."""
        artifacts = []

        # Mermaid diagrams (always artifact)
        for match in self.MERMAID_PATTERN.finditer(content):
            artifacts.append(DetectedArtifact(
                artifact_type="mermaid",
                content=match.group(1).strip(),
                title=self._extract_mermaid_title(match.group(1)),
                span=(match.start(), match.end()),
            ))

        # HTML documents (>500 chars or contains <html>)
        for match in self.HTML_PATTERN.finditer(content):
            html_content = match.group(1).strip()
            if len(html_content) > 500 or "<html" in html_content.lower():
                artifacts.append(DetectedArtifact(
                    artifact_type="html",
                    content=html_content,
                    title=self._extract_html_title(html_content),
                    span=(match.start(), match.end()),
                ))

        # Code blocks (>15 lines, not already matched as HTML/Mermaid)
        for match in self.CODE_PATTERN.finditer(content):
            lang = match.group(1) or "text"
            code = match.group(2).strip()

            # Skip if already matched as mermaid or html
            if lang.lower() in ("mermaid", "html", "htm"):
                continue

            if code.count("\n") >= self.MIN_CODE_LINES:
                artifacts.append(DetectedArtifact(
                    artifact_type="code",
                    content=code,
                    title=self._extract_code_title(code, lang),
                    language=lang,
                    span=(match.start(), match.end()),
                ))

        # Large tables (>10 rows)
        for match in self.TABLE_PATTERN.finditer(content):
            table = match.group(1).strip()
            row_count = table.count("\n")
            if row_count >= self.MIN_TABLE_ROWS:
                artifacts.append(DetectedArtifact(
                    artifact_type="table",
                    content=table,
                    title="Data Table",
                    span=(match.start(), match.end()),
                ))

        return artifacts

    async def save(
        self, artifact: DetectedArtifact, conversation_id: int, message_id: int
    ) -> int:
        """Save an artifact to the database. Returns artifact ID."""
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO public.bh_artifacts
                    (conversation_id, message_id, artifact_type, title, content, language)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            """, conversation_id, message_id, artifact.artifact_type,
                artifact.title, artifact.content, artifact.language)
        return row["id"]

    async def save_version(
        self, parent_id: int, artifact: DetectedArtifact,
        conversation_id: int, message_id: int
    ) -> int:
        """Save a new version of an existing artifact."""
        pool = get_pool()
        async with pool.acquire() as conn:
            # Get current version number
            current = await conn.fetchval(
                "SELECT MAX(version) FROM public.bh_artifacts WHERE id = $1 OR parent_id = $1",
                parent_id,
            )
            new_version = (current or 1) + 1

            row = await conn.fetchrow("""
                INSERT INTO public.bh_artifacts
                    (conversation_id, message_id, artifact_type, title, content,
                     language, version, parent_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
            """, conversation_id, message_id, artifact.artifact_type,
                artifact.title, artifact.content, artifact.language,
                new_version, parent_id)
        return row["id"]

    async def get_versions(self, artifact_id: int) -> List[Dict[str, Any]]:
        """Get all versions of an artifact."""
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, version, title, created_at
                FROM public.bh_artifacts
                WHERE id = $1 OR parent_id = $1
                ORDER BY version DESC
            """, artifact_id)
        return [dict(r) for r in rows]

    async def save_to_disk(self, artifact_id: int, workspace_name: str) -> str:
        """Save artifact content to disk. Returns the file path."""
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM public.bh_artifacts WHERE id = $1", artifact_id
            )

        if not row:
            raise ValueError("Artifact not found")

        # Determine file extension
        ext_map = {
            "code": f".{row['language']}" if row["language"] else ".txt",
            "html": ".html",
            "mermaid": ".mmd",
            "chart": ".json",
            "markdown": ".md",
            "table": ".md",
        }
        ext = ext_map.get(row["artifact_type"], ".txt")

        # Generate slug from title
        slug = re.sub(r'[^a-z0-9]+', '-', row["title"].lower()).strip('-')[:50]
        if not slug:
            slug = str(uuid.uuid4())[:8]

        # Write to disk
        artifact_dir = self.files_root / "artifacts" / workspace_name.lower()
        artifact_dir.mkdir(parents=True, exist_ok=True)
        file_path = artifact_dir / f"{slug}{ext}"
        file_path.write_text(row["content"])

        # Update DB with file path
        rel_path = str(file_path.relative_to(self.files_root))
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE public.bh_artifacts SET file_path = $1 WHERE id = $2",
                rel_path, artifact_id,
            )

        return rel_path

    def process_response(self, content: str) -> Tuple[str, List[DetectedArtifact]]:
        """
        Process an AI response: detect artifacts and return modified content
        with artifact reference markers replacing the original content.
        """
        artifacts = self.detect(content)
        if not artifacts:
            return content, []

        # Replace artifact content with reference markers (process in reverse to preserve spans)
        modified = content
        for i, artifact in enumerate(sorted(artifacts, key=lambda a: a.span[0], reverse=True)):
            start, end = artifact.span
            marker = f"\n\n[📎 Artifact: {artifact.title} ({artifact.artifact_type})]\n\n"
            modified = modified[:start] + marker + modified[end:]

        return modified, artifacts

    # --- Title extraction helpers ---

    def _extract_code_title(self, code: str, language: str) -> str:
        """Try to extract a meaningful title from code."""
        lines = code.split("\n")[:5]
        for line in lines:
            # Look for function/class definitions
            if re.match(r'(def|class|function|const|export)\s+\w+', line):
                name = re.search(r'(def|class|function|const|export)\s+(\w+)', line)
                if name:
                    return f"{name.group(2)} ({language})"
            # Look for comments
            if line.strip().startswith(("#", "//", "/*")):
                comment = line.strip().lstrip("#/ *").strip()
                if len(comment) > 3:
                    return comment[:60]
        return f"Code ({language})"

    def _extract_html_title(self, html: str) -> str:
        """Extract title from HTML content."""
        match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
        if match:
            return match.group(1)[:60]
        match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE)
        if match:
            return re.sub(r'<[^>]+>', '', match.group(1))[:60]
        return "HTML Document"

    def _extract_mermaid_title(self, content: str) -> str:
        """Extract title from Mermaid diagram."""
        first_line = content.split("\n")[0].strip()
        if "graph" in first_line or "flowchart" in first_line:
            return "Flowchart"
        elif "sequenceDiagram" in first_line:
            return "Sequence Diagram"
        elif "classDiagram" in first_line:
            return "Class Diagram"
        elif "gantt" in first_line:
            return "Gantt Chart"
        elif "pie" in first_line:
            return "Pie Chart"
        return "Diagram"
