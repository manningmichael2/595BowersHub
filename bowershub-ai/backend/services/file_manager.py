"""
File Manager: upload, resize, store, serve files, and manage knowledge base files.
"""

import hashlib
import io
import logging
import mimetypes
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.config import Config
from backend.database import get_pool

logger = logging.getLogger(__name__)

ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "application/pdf",
    "text/plain", "text/markdown", "text/csv",
}

BLOCKED_EXTENSIONS = {
    ".exe", ".sh", ".bat", ".cmd", ".ps1", ".py", ".js",
    ".msi", ".dll", ".so", ".dylib", ".com", ".vbs",
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
IMAGE_RESIZE_THRESHOLD = 4 * 1024 * 1024  # 4MB


class FileValidationError(Exception):
    pass


class FileManager:
    """Handles file uploads, storage, resizing, and knowledge base operations."""

    def __init__(self, config: Config):
        self.files_root = Path(config.FILES_ROOT)
        self.knowledge_root = Path(config.KNOWLEDGE_ROOT)

    # --- File Upload ---

    async def upload(
        self, file_content: bytes, filename: str, mime_type: str,
        conversation_id: int, user_id: int
    ) -> Dict[str, Any]:
        """
        Upload a file: validate, store, create asset record.
        Returns asset metadata dict.
        """
        # Validate
        self._validate_upload(file_content, filename, mime_type)

        # Generate storage path
        ext = Path(filename).suffix.lower()
        asset_id = str(uuid.uuid4())
        rel_path = f"chat-uploads/{conversation_id}/{asset_id}{ext}"
        full_path = self.files_root / rel_path

        # Ensure directory exists
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Resize image if needed
        if mime_type.startswith("image/") and len(file_content) > IMAGE_RESIZE_THRESHOLD:
            file_content = self._resize_image(file_content, mime_type)

        # Write file
        full_path.write_bytes(file_content)

        # Compute sha256
        sha256 = hashlib.sha256(file_content).hexdigest()

        # Create asset record in DB
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO files.assets
                    (path, original_name, mime, size_bytes, sha256, domain, uploaded_by)
                VALUES ($1, $2, $3, $4, $5, 'chat', $6)
                ON CONFLICT (sha256) DO UPDATE SET path = EXCLUDED.path
                RETURNING id, path, mime, size_bytes, sha256, ai_summary
            """, str(rel_path), filename, mime_type, len(file_content), sha256, str(user_id))

        return {
            "asset_id": str(row["id"]),
            "path": row["path"],
            "filename": filename,
            "mime": mime_type,
            "size_bytes": len(file_content),
            "sha256": sha256,
        }

    def _validate_upload(self, content: bytes, filename: str, mime_type: str):
        """Validate file before storage."""
        if len(content) > MAX_FILE_SIZE:
            raise FileValidationError(f"File too large ({len(content)} bytes). Maximum is 10MB.")

        ext = Path(filename).suffix.lower()
        if ext in BLOCKED_EXTENSIONS:
            raise FileValidationError(f"File type '{ext}' is not allowed.")

        if mime_type not in ALLOWED_MIME_TYPES:
            # Check if it's a subtype we allow
            major = mime_type.split("/")[0]
            if major not in ("image", "text"):
                raise FileValidationError(f"File type '{mime_type}' is not allowed.")

    def _resize_image(self, content: bytes, mime_type: str) -> bytes:
        """Resize image to fit within 4MB using Pillow."""
        try:
            from PIL import Image

            img = Image.open(io.BytesIO(content))
            # Reduce quality/size iteratively
            quality = 85
            while len(content) > IMAGE_RESIZE_THRESHOLD and quality > 20:
                # Scale down
                factor = (IMAGE_RESIZE_THRESHOLD / len(content)) ** 0.5
                new_size = (int(img.width * factor), int(img.height * factor))
                img = img.resize(new_size, Image.LANCZOS)

                buf = io.BytesIO()
                fmt = "JPEG" if "jpeg" in mime_type or "jpg" in mime_type else "PNG"
                img.save(buf, format=fmt, quality=quality, optimize=True)
                content = buf.getvalue()
                quality -= 10

            logger.info(f"Image resized to {len(content)} bytes")
            return content
        except ImportError:
            logger.warning("Pillow not available — skipping image resize")
            return content

    # --- File Serving ---

    def get_file_path(self, rel_path: str) -> Optional[Path]:
        """Get absolute path for a file, with traversal protection."""
        full_path = (self.files_root / rel_path).resolve()
        # Ensure it's within files_root
        if not str(full_path).startswith(str(self.files_root.resolve())):
            return None
        if not full_path.exists():
            return None
        return full_path

    def get_thumbnail_path(self, rel_path: str, max_width: int = 200) -> Optional[Path]:
        """Get or generate a thumbnail for an image."""
        full_path = self.get_file_path(rel_path)
        if not full_path:
            return None

        # Check if it's an image
        mime, _ = mimetypes.guess_type(str(full_path))
        if not mime or not mime.startswith("image/"):
            return None

        # Generate thumbnail path
        thumb_dir = self.files_root / ".thumbnails"
        thumb_dir.mkdir(exist_ok=True)
        thumb_path = thumb_dir / f"{full_path.stem}_{max_width}{full_path.suffix}"

        if thumb_path.exists():
            return thumb_path

        # Generate thumbnail
        try:
            from PIL import Image
            img = Image.open(full_path)
            img.thumbnail((max_width, max_width), Image.LANCZOS)
            img.save(thumb_path, quality=80, optimize=True)
            return thumb_path
        except Exception:
            return full_path  # Fall back to original

    # --- PDF Text Extraction ---

    def extract_pdf_text(self, content: bytes, max_chars: int = 50000) -> str:
        """Extract text from a PDF file."""
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                text_parts = []
                total_chars = 0
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    if total_chars + len(page_text) > max_chars:
                        text_parts.append(page_text[:max_chars - total_chars])
                        break
                    text_parts.append(page_text)
                    total_chars += len(page_text)
                return "\n\n".join(text_parts)
        except ImportError:
            logger.warning("pdfplumber not available — cannot extract PDF text")
            return "[PDF text extraction unavailable]"
        except Exception as e:
            logger.warning(f"PDF extraction failed: {e}")
            return "[Failed to extract PDF text]"

    # --- Image to Base64 ---

    def image_to_base64(self, content: bytes) -> str:
        """Convert image bytes to base64 string."""
        import base64
        return base64.b64encode(content).decode("utf-8")

    # --- Knowledge Base Operations ---

    async def read_knowledge(self, topic: str) -> Optional[str]:
        """Read a knowledge file by topic."""
        safe_topic = topic.replace("..", "").strip("/")
        file_path = self.knowledge_root / f"{safe_topic}.md"
        if file_path.exists():
            return file_path.read_text()
        return None

    async def append_knowledge(self, topic: str, line: str):
        """Append a line to a knowledge file."""
        safe_topic = topic.replace("..", "").strip("/")
        file_path = self.knowledge_root / f"{safe_topic}.md"
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if not file_path.exists():
            header = f"# {topic.split('/')[-1].replace('-', ' ').title()}\n\n"
            file_path.write_text(header + line + "\n")
        else:
            with open(file_path, "a") as f:
                f.write(line + "\n")

    async def search_knowledge(self, query: str) -> List[Dict[str, str]]:
        """Search knowledge base files for a query string."""
        results = []
        query_lower = query.lower()

        if not self.knowledge_root.exists():
            return results

        for md_file in self.knowledge_root.rglob("*.md"):
            try:
                content = md_file.read_text()
                if query_lower in content.lower():
                    # Find matching lines
                    for line in content.split("\n"):
                        if query_lower in line.lower():
                            rel_path = str(md_file.relative_to(self.knowledge_root))
                            results.append({
                                "file": rel_path,
                                "topic": md_file.stem.replace("-", " ").title(),
                                "match": line.strip(),
                            })
            except Exception:
                continue

        return results[:50]  # Cap results
