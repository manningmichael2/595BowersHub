"""
Knowledge Memory — native Python implementation of recall + remember.

Replaces the n8n Knowledge Memory workflow (9fTh1G0THWgI6XB3).

- remember: saves a fact to /knowledge/<topic>.md with dedup via local Ollama
- recall: searches /knowledge/ via filewriter's /search endpoint
"""
import logging
import re
from datetime import date
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

FILEWRITER_URL = "http://100.106.180.101:5001"
OLLAMA_URL = "http://ollama:11434"
KNOWLEDGE_ROOT = "/knowledge"


# ---- Recall ---------------------------------------------------------------

async def recall(query: str) -> dict:
    """
    Search the knowledge base for facts matching a query.
    Uses filewriter's /search endpoint with smart mode.
    """
    if not query or not query.strip():
        return {"error": "Provide a search query."}

    query = query.strip()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{FILEWRITER_URL}/search",
                json={"root": KNOWLEDGE_ROOT, "query": query, "mode": "smart"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return {"error": f"Knowledge search failed: {e}"}

    results = data.get("results", data.get("matches", []))
    if not results:
        return {
            "query": query,
            "results": [],
            "_display": f"No results found for **\"{query}\"** in the knowledge base.",
        }

    # Group matches by file
    from collections import defaultdict
    by_file: dict[str, list[str]] = defaultdict(list)
    matched_files: set[str] = set()

    for match in results:
        file_path = match.get("file", "")
        line = match.get("line", "") if "line" in match else ""
        if "lines" in match:
            for l in match["lines"]:
                by_file[match.get("file", match.get("topic", ""))].append(l)
        elif line:
            by_file[file_path].append(line)
        if file_path:
            matched_files.add(file_path)

    # For files where we only got header/filename matches, fetch the full
    # file content so the user sees the actual facts, not just the title.
    for file_path in list(matched_files):
        lines_so_far = by_file.get(file_path, [])
        # If we only got 1-2 lines and they're all headers/metadata, read the full file
        non_header_lines = [l for l in lines_so_far if not l.startswith("# ") and not l.startswith("> ")]
        if len(non_header_lines) <= 1:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(
                        f"{FILEWRITER_URL}/read-text",
                        json={"path": file_path},
                    )
                    if resp.status_code == 200:
                        file_data = resp.json()
                        content = file_data.get("content", "")
                        if content:
                            # Replace with full file lines (skip empty lines)
                            by_file[file_path] = [
                                l for l in content.split("\n")
                                if l.strip() and not l.startswith("# ")
                            ]
            except Exception:
                pass  # Keep whatever we had

    if not by_file:
        return {
            "query": query,
            "results": [],
            "_display": f"No results found for **\"{query}\"** in the knowledge base.",
        }

    # Build beautiful display
    lines = [f"## 🧠 Knowledge: \"{query}\"", ""]

    for file_path, file_lines in by_file.items():
        # Clean up topic from file path for display
        topic = file_path.replace(KNOWLEDGE_ROOT + "/", "").replace(".md", "")
        display_topic = topic.replace("/", " › ").replace("-", " ").title()
        lines.append(f"### {display_topic}")

        for line in file_lines:
            # Strip the date prefix for cleaner display but keep it subtle
            cleaned = re.sub(r"^- \[(\d{4}-\d{2}-\d{2})\] ", r"- *(\1)* ", line)
            if cleaned.startswith("# "):
                pass  # Skip headers (already shown as ### above)
            elif cleaned.strip():
                if not cleaned.startswith("- "):
                    cleaned = f"- {cleaned.strip()}"
                lines.append(cleaned)

        lines.append("")

    display = "\n".join(lines)

    return {
        "query": query,
        "results": results,
        "_display": display,
    }


# ---- Remember -------------------------------------------------------------

async def remember(topic: str, fact: str) -> dict:
    """
    Save a fact to /knowledge/<topic>.md.
    Deduplicates via local Ollama model before saving.
    """
    if not topic or not topic.strip():
        return {"error": "Missing required parameter: topic"}
    if not fact or not fact.strip():
        return {"error": "Missing required parameter: fact"}

    topic = topic.strip()
    fact = fact.strip()

    # Normalize topic to filesystem-safe path
    normalized = (
        topic.lower()
        .replace(" ", "-")
        .strip()
    )
    normalized = re.sub(r"[^a-z0-9_/-]+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized)
    normalized = normalized.strip("/-")

    if not normalized:
        return {"error": "Topic normalized to empty string. Use letters, numbers, hyphens, or slashes."}

    path = f"{KNOWLEDGE_ROOT}/{normalized}.md"
    today = date.today().isoformat()

    # Read existing content
    existing_content = ""
    file_exists = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{FILEWRITER_URL}/read-text",
                json={"path": path},
            )
            if resp.status_code == 200:
                data = resp.json()
                file_exists = data.get("exists", False)
                existing_content = data.get("content", "").strip()
    except Exception:
        pass  # If read fails, treat as new file

    # Dedup check — only if file has existing content
    should_save = True
    dedup_reason = "new entry"

    if existing_content:
        dedup_result = await _check_dedup(normalized, existing_content, fact)
        should_save = not dedup_result.get("covered", False)
        dedup_reason = dedup_result.get("reason", "")

    if not should_save:
        return {
            "saved": False,
            "topic": normalized,
            "fact": fact,
            "reason": dedup_reason,
            "_display": f"ℹ️ Fact already covered in **{normalized}**: {dedup_reason}",
        }

    # Save the fact
    line = f"- [{today}] {fact}"
    header = f"# {topic.replace('/', ' / ')}\n\n" if not file_exists else ""
    content = header + line

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{FILEWRITER_URL}/append",
                json={"path": path, "content": content},
            )
            resp.raise_for_status()
    except Exception as e:
        return {"error": f"Failed to save: {e}"}

    return {
        "saved": True,
        "topic": normalized,
        "path": path,
        "fact": fact,
        "_display": f"✅ Saved to **{normalized}**: {fact}",
    }


async def _check_dedup(topic: str, existing: str, new_fact: str) -> dict:
    """Check if a fact is already covered using local Ollama model."""
    prompt = (
        f"TOPIC: {topic}\n\n"
        f"EXISTING KNOWLEDGE:\n{existing}\n\n"
        f"NEW FACT: {new_fact}\n\n"
        "Is the new fact already substantively covered by the existing content? "
        "Paraphrases ARE duplicates. Conflicting facts are NOT duplicates. "
        "New details that add specificity are NOT duplicates.\n"
        "Return ONLY JSON: {\"covered\": true/false, \"reason\": \"short explanation\"}"
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": "llama3.2:3b",
                    "messages": [
                        {"role": "system", "content": "You are a deduplication classifier. Return ONLY the JSON object requested."},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": 0, "num_predict": 100},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("message", {}).get("content", "")

            # Parse JSON from response
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            
            import json
            return json.loads(content)

    except Exception as e:
        # On failure, default to NOT covered (safer to save a possible dup than lose a fact)
        logger.warning(f"Knowledge dedup check failed: {e}")
        return {"covered": False, "reason": "dedup_check_failed"}
