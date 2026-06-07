"""
Filewriter — small HTTP service for filesystem ops n8n can't easily do itself.

Originally built to write JSON transaction files (the /write endpoint).
Extended (May 2026) to support the Process Asset pipeline:
  - probe a file (size, sha256, mime)
  - read a file as base64 (for vision)
  - move a file with mkdir -p on the destination

All paths are validated to stay within ALLOWED_ROOTS to prevent traversal.
No auth — internal Docker network only.
"""
import base64
import hashlib
import json
import mimetypes
import os
import re
import shutil

from flask import Flask, request, jsonify
import io
from PIL import Image

# Stopwords used by /search mode=smart. Tokens that carry no signal in a
# personal-knowledge recall query ("what have I written about manon's allergies?"
# should match on `manon` + `allergies`, not on `what`/`have`/`about`).
_SEARCH_STOPWORDS = frozenset({
    "a", "an", "and", "any", "are", "as", "at", "be", "been", "but", "by",
    "can", "did", "do", "does", "for", "from", "had", "has", "have", "he",
    "her", "hers", "him", "his", "how", "i", "if", "in", "into", "is",
    "it", "its", "me", "mine", "my", "of", "on", "or", "our", "ours", "out",
    "she", "so", "some", "than", "that", "the", "their", "theirs", "them",
    "then", "there", "these", "they", "this", "those", "to", "us", "was",
    "we", "were", "what", "when", "where", "which", "who", "whose", "why",
    "will", "with", "would", "you", "your", "yours",
    # Domain-specific noise from how users phrase recall queries.
    "about", "anything", "know", "remember", "recall", "saved", "say", "said",
    "tell", "told", "wrote", "written", "note", "notes", "thing", "things",
    "stuff",
})

def _smart_tokens(query: str):
    """Tokenize a free-form query for smart search.

    - Lowercase, split on non-alphanumeric.
    - Drop stopwords and tokens shorter than 3 characters.
    - Deduplicate while preserving order.
    Returns a list of token strings (possibly empty if the user typed only
    stopwords / very short words).
    """
    raw = re.split(r"[^a-z0-9]+", (query or "").lower())
    seen = []
    seen_set = set()
    for tok in raw:
        if not tok or len(tok) < 3 or tok in _SEARCH_STOPWORDS:
            continue
        if tok in seen_set:
            continue
        seen_set.add(tok)
        seen.append(tok)
    return seen

def _filename_tokens(fpath: str):
    """Tokens derived from the relative filename so a query like
    'manon allergies' hits cooking/manon-allergies.md even if the body of
    the file doesn't contain both words on one line."""
    base = os.path.splitext(os.path.basename(fpath))[0]
    parent = os.path.basename(os.path.dirname(fpath)) or ""
    raw = re.split(r"[^a-z0-9]+", (parent + " " + base).lower())
    return {t for t in raw if t and len(t) >= 3 and t not in _SEARCH_STOPWORDS}

def _shrink_image_if_needed(path, max_bytes):
    """If file is an image and exceeds max_bytes, return resized JPEG bytes.
    Otherwise return raw file bytes."""
    with open(path, 'rb') as f:
        raw = f.read()

    if len(raw) <= max_bytes:
        return raw, len(raw)

    # Try to resize as image
    try:
        img = Image.open(io.BytesIO(raw))
        # Convert to RGB (handles RGBA, CMYK, etc.)
        if img.mode != 'RGB':
            img = img.convert('RGB')

        # Iteratively reduce dimensions until under max_bytes
        max_dim = max(img.size)
        while True:
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=85, optimize=True)
            if buf.tell() <= max_bytes or max_dim < 800:
                break
            # Reduce dimensions by 20%
            max_dim = int(max_dim * 0.8)
            ratio = max_dim / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        return buf.getvalue(), buf.tell()
    except Exception:
        # Not an image or failed to resize — return original (caller will reject)
        return raw, len(raw)


app = Flask(__name__)

# Roots the service is allowed to operate inside. Anything outside is rejected.
ALLOWED_ROOTS = [
    "/finance",   # legacy: transaction JSON files
    "/files",     # new: the household file repository
    "/knowledge", # personal knowledge base (markdown, agent-managed memory)
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resolve(path: str) -> str:
    """Normalize and validate that `path` falls under one of the allowed roots."""
    if not path or not isinstance(path, str):
        raise ValueError("path is required")
    norm = os.path.normpath(path)
    if not norm.startswith("/"):
        raise ValueError("path must be absolute")
    for root in ALLOWED_ROOTS:
        if norm == root or norm.startswith(root + "/"):
            return norm
    raise ValueError(f"path '{norm}' is outside allowed roots {ALLOWED_ROOTS}")


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _mime(path: str) -> str:
    # Prefer python's built-in guess (fast). Falls back to octet-stream.
    guess, _ = mimetypes.guess_type(path)
    return guess or "application/octet-stream"


# ---------------------------------------------------------------------------
# Legacy: write a JSON file under /finance
# ---------------------------------------------------------------------------
@app.route("/write", methods=["POST"])
def write():
    payload = request.get_json(force=True) or {}
    filename = payload.get("filename", "transactions.json")
    data = payload.get("data")
    filepath = f"/finance/{filename}"
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    return {"success": True, "file": filename}


# ---------------------------------------------------------------------------
# Probe — return existence, size, sha256, mime for a file
# ---------------------------------------------------------------------------
@app.route("/probe", methods=["POST"])
def probe():
    body = request.get_json(force=True) or {}
    try:
        path = _resolve(body.get("path"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    if not os.path.isfile(path):
        return jsonify({"ok": True, "exists": False, "path": path})

    return jsonify({
        "ok": True,
        "exists": True,
        "path": path,
        "size_bytes": os.path.getsize(path),
        "sha256": _sha256(path),
        "mime": _mime(path),
    })


# ---------------------------------------------------------------------------
# Read base64 — return the file contents base64-encoded (for image vision)
# ---------------------------------------------------------------------------
@app.route("/read-base64", methods=["POST"])
def read_base64():
    body = request.get_json(force=True) or {}
    try:
        path = _resolve(body.get("path"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": "not found", "path": path}), 404

    # Cap at max_bytes — for images, auto-resize if over.
    # Default to 5 MB (Anthropic API limit).
    max_bytes = body.get("max_bytes", 5 * 1024 * 1024)
    raw, size = _shrink_image_if_needed(path, max_bytes)
    if size > max_bytes:
        return jsonify({
            "ok": False,
            "error": f"file too large after resize ({size} > {max_bytes})",
            "path": path,
        }), 413

    b64 = base64.b64encode(raw).decode("ascii")
    return jsonify({"ok": True, "path": path, "size_bytes": size, "base64": b64, "resized": size != os.path.getsize(path)})


# ---------------------------------------------------------------------------
# Move — move a file, creating destination directory if needed.
# Body: {"src": "/files/inbox/x.jpg", "dst": "/files/receipts/2026/<uuid>.jpg"}
# ---------------------------------------------------------------------------
@app.route("/move", methods=["POST"])
def move():
    body = request.get_json(force=True) or {}
    try:
        src = _resolve(body.get("src"))
        dst = _resolve(body.get("dst"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    if not os.path.isfile(src):
        return jsonify({"ok": False, "error": "source not found", "src": src}), 404

    if src == dst:
        return jsonify({"ok": True, "moved": False, "reason": "src == dst", "path": dst})

    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    return jsonify({"ok": True, "moved": True, "path": dst})


# ---------------------------------------------------------------------------
# Mkdir — create a directory tree under an allowed root.
# ---------------------------------------------------------------------------
@app.route("/mkdir", methods=["POST"])
def mkdir():
    body = request.get_json(force=True) or {}
    try:
        path = _resolve(body.get("path"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    os.makedirs(path, exist_ok=True)
    return jsonify({"ok": True, "path": path})


# ---------------------------------------------------------------------------
# Write base64 — decode and persist a file under an allowed root.
# Used by the email importer to land Gmail attachments into /files/inbox.
# Body: {"path": "/files/inbox/<name>", "base64": "...", "overwrite": false}
# ---------------------------------------------------------------------------
@app.route("/write-base64", methods=["POST"])
def write_base64():
    body = request.get_json(force=True) or {}
    try:
        path = _resolve(body.get("path"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    b64 = body.get("base64")
    if not b64 or not isinstance(b64, str):
        return jsonify({"ok": False, "error": "missing base64"}), 400

    overwrite = bool(body.get("overwrite", False))
    if os.path.exists(path) and not overwrite:
        return jsonify({"ok": False, "error": "file exists; pass overwrite=true to replace", "path": path}), 409

    try:
        data = base64.b64decode(b64, validate=True)
    except Exception as e:
        return jsonify({"ok": False, "error": f"invalid base64: {e}"}), 400

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return jsonify({"ok": True, "path": path, "size_bytes": len(data)})


# ---------------------------------------------------------------------------
# Append text — append a string to a file under an allowed root.
# Body: {"path": "/knowledge/finance.md", "content": "..."}
# Creates the file (and parent dirs) if it doesn't exist.
# ---------------------------------------------------------------------------
@app.route("/append", methods=["POST"])
def append():
    body = request.get_json(force=True) or {}
    try:
        path = _resolve(body.get("path"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    content = body.get("content")
    if content is None or not isinstance(content, str):
        return jsonify({"ok": False, "error": "content (string) is required"}), 400

    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Ensure trailing newline so successive appends don't run together.
    if not content.endswith("\n"):
        content = content + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(content)

    return jsonify({"ok": True, "path": path, "bytes_written": len(content.encode("utf-8"))})


# ---------------------------------------------------------------------------
# Read text — return the full text contents of a file (utf-8).
# Body: {"path": "/knowledge/finance.md"}
# ---------------------------------------------------------------------------
@app.route("/read-text", methods=["POST"])
def read_text():
    body = request.get_json(force=True) or {}
    try:
        path = _resolve(body.get("path"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    if not os.path.isfile(path):
        return jsonify({"ok": True, "exists": False, "path": path, "content": ""})

    # Cap text reads at 1 MB. Knowledge files should never approach this.
    size = os.path.getsize(path)
    max_bytes = body.get("max_bytes", 1 * 1024 * 1024)
    if size > max_bytes:
        return jsonify({
            "ok": False,
            "error": f"file too large ({size} > {max_bytes})",
            "path": path,
        }), 413

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return jsonify({"ok": True, "exists": True, "path": path, "size_bytes": size, "content": content})


# ---------------------------------------------------------------------------
# Search — grep-style search across a directory under an allowed root.
# Body: {"root": "/knowledge", "query": "ally", "case_insensitive": true,
#         "mode": "literal" | "smart"}
#
# - mode="literal" (default): treat the entire query as one substring; match
#   any line that contains it. Same behavior as before.
# - mode="smart":  tokenize the query (drop stopwords, words <3 chars), match
#   any line that contains ANY meaningful token, and also include files whose
#   path/filename contains any token (so 'manon allergies' hits the file
#   cooking/manon-allergies.md even if no line carries both words). Results
#   are ranked by per-file token-hit count.
# Returns a list of {file, line_number, line} matches.
# ---------------------------------------------------------------------------
@app.route("/search", methods=["POST"])
def search():
    body = request.get_json(force=True) or {}
    try:
        root = _resolve(body.get("root"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    query = body.get("query")
    if not query or not isinstance(query, str):
        return jsonify({"ok": False, "error": "query (string) is required"}), 400

    case_insensitive = bool(body.get("case_insensitive", True))
    extensions = body.get("extensions", [".md", ".txt"])
    max_results = int(body.get("max_results", 100))
    mode = (body.get("mode") or "literal").lower()

    if not os.path.isdir(root):
        return jsonify({"ok": True, "root": root, "matches": [], "exists": False})

    # ---- smart mode (tokenized OR-match + filename matching) -------------
    if mode == "smart":
        tokens = _smart_tokens(query)
        if not tokens:
            # No usable tokens after stopword stripping. Fall back to literal
            # so the caller still gets a deterministic answer.
            mode = "literal"
        else:
            file_hits = []  # list of (score, file, lines)
            for dirpath, _, filenames in os.walk(root):
                for fname in filenames:
                    if extensions and not any(fname.endswith(ext) for ext in extensions):
                        continue
                    fpath = os.path.join(dirpath, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                            content_lines = f.readlines()
                    except (OSError, UnicodeDecodeError):
                        continue

                    # Per-file token hit set + matching lines.
                    hits = set()
                    matched_lines = []
                    fname_tokens = _filename_tokens(fpath)
                    for tok in tokens:
                        if tok in fname_tokens:
                            hits.add(tok)
                    for i, line in enumerate(content_lines, start=1):
                        hay = line.lower()
                        line_tokens_hit = [t for t in tokens if t in hay]
                        if line_tokens_hit:
                            for t in line_tokens_hit:
                                hits.add(t)
                            matched_lines.append({
                                "line_number": i,
                                "line": line.rstrip("\n"),
                            })

                    if not hits:
                        continue

                    # If the file matched only by filename (no body lines), surface
                    # the topic header so the caller has something to display.
                    if not matched_lines and content_lines:
                        matched_lines.append({
                            "line_number": 1,
                            "line": content_lines[0].rstrip("\n"),
                        })

                    file_hits.append((len(hits), fpath, matched_lines))

            # Sort: most distinct tokens hit first, then alpha by path.
            file_hits.sort(key=lambda x: (-x[0], x[1]))

            # Relevance filter: when the query has 2+ meaningful tokens, only
            # return files that hit the maximum observed score. A query like
            # "manon allergies" should not return a file that only mentions
            # Manon. With a single-token query we have no signal to filter on,
            # so keep everything.
            if file_hits and len(tokens) >= 2:
                top_score = file_hits[0][0]
                file_hits = [fh for fh in file_hits if fh[0] >= top_score]

            matches = []
            truncated = False
            for _, fpath, matched_lines in file_hits:
                for ml in matched_lines:
                    matches.append({
                        "file": fpath,
                        "line_number": ml["line_number"],
                        "line": ml["line"],
                    })
                    if len(matches) >= max_results:
                        truncated = True
                        break
                if truncated:
                    break

            return jsonify({
                "ok": True,
                "root": root,
                "query": query,
                "mode": "smart",
                "tokens": tokens,
                "match_count": len(matches),
                "truncated": truncated,
                "matches": matches,
            })

    # ---- literal mode (original behavior) --------------------------------
    needle = query.lower() if case_insensitive else query

    matches = []
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            if extensions and not any(fname.endswith(ext) for ext in extensions):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, start=1):
                        hay = line.lower() if case_insensitive else line
                        if needle in hay:
                            matches.append({
                                "file": fpath,
                                "line_number": i,
                                "line": line.rstrip("\n"),
                            })
                            if len(matches) >= max_results:
                                return jsonify({
                                    "ok": True,
                                    "root": root,
                                    "query": query,
                                    "match_count": len(matches),
                                    "truncated": True,
                                    "matches": matches,
                                })
            except (OSError, UnicodeDecodeError):
                # Skip unreadable / binary files silently.
                continue

    return jsonify({
        "ok": True,
        "root": root,
        "query": query,
        "match_count": len(matches),
        "truncated": False,
        "matches": matches,
    })


# ---------------------------------------------------------------------------
# IMAP endpoints — Gmail App Password access for inbox automation.
#
# These are stateless: each call opens a fresh connection, does its thing,
# closes. No long-lived IMAP state. This makes activation/deactivation safe
# even on huge inboxes — caller controls batch size and time window.
#
# Auth is read from env vars, NOT request body, to avoid leaking the App
# Password through n8n logs:
#   GMAIL_IMAP_USER     = manningmichael2@gmail.com
#   GMAIL_IMAP_PASSWORD = <16-char App Password>
#
# Library: imap-tools (clean wrapper around stdlib imaplib).
# ---------------------------------------------------------------------------
def _imap_connect():
    """Open an IMAP connection to Gmail. Caller MUST close via context manager."""
    from imap_tools import MailBox
    user = os.environ.get("GMAIL_IMAP_USER")
    pw = os.environ.get("GMAIL_IMAP_PASSWORD")
    if not user or not pw:
        raise RuntimeError("GMAIL_IMAP_USER / GMAIL_IMAP_PASSWORD env vars not set")
    return MailBox("imap.gmail.com").login(user, pw, initial_folder="INBOX")


@app.route("/imap/fetch-recent", methods=["POST"])
def imap_fetch_recent():
    """Fetch a small bounded batch of recent emails for classification.

    Body:
      {
        "folder": "INBOX",                   # IMAP folder/label name
        "since_minutes": 30,                 # only consider emails newer than this
        "limit": 10,                          # hard cap on results
        "exclude_message_ids": ["..."],      # already-processed ids (dedup)
        "include_body": true,                # include text body in response
        "body_max_chars": 5000               # truncate body
      }

    Returns:
      {
        ok: true,
        folder: "INBOX",
        count: N,
        emails: [
          {
            uid, message_id, subject, from_address, from_name, date,
            body_text, has_attachments, attachment_count
          }, ...
        ]
      }
    """
    from imap_tools import AND
    from datetime import datetime, timedelta, timezone

    body = request.get_json(force=True) or {}
    folder = body.get("folder", "INBOX")
    since_minutes = int(body.get("since_minutes", 30))
    limit = min(int(body.get("limit", 10)), 50)  # hard cap at 50 regardless
    exclude_ids = set(body.get("exclude_message_ids") or [])
    include_body = bool(body.get("include_body", True))
    body_max_chars = int(body.get("body_max_chars", 5000))

    since_date = (datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).date()

    out = []
    try:
        with _imap_connect() as mb:
            mb.folder.set(folder)
            # Search for messages since the cutoff date. IMAP SINCE is a date,
            # not a datetime, so we get a slightly larger window — fine, dedup
            # at the application layer handles overlap.
            criteria = AND(date_gte=since_date)
            # Iterate in reverse so newest first; bail when limit hit.
            for msg in mb.fetch(criteria, reverse=True, mark_seen=False, bulk=False, limit=limit * 3):
                msg_id = msg.headers.get("message-id", (msg.uid,))[0] if msg.headers.get("message-id") else f"uid:{msg.uid}"
                # Strip surrounding < > if present
                if msg_id.startswith("<") and msg_id.endswith(">"):
                    msg_id = msg_id[1:-1]
                if msg_id in exclude_ids:
                    continue
                out.append({
                    "uid": msg.uid,
                    "message_id": msg_id,
                    "subject": msg.subject or "",
                    "from_address": msg.from_ or "",
                    "from_name": msg.from_values.name if msg.from_values else "",
                    "date": msg.date_str or "",
                    "body_text": ((msg.text or msg.html or "")[:body_max_chars]) if include_body else "",
                    "has_attachments": len(msg.attachments) > 0,
                    "attachment_count": len(msg.attachments),
                })
                if len(out) >= limit:
                    break
    except Exception as e:
        return jsonify({"ok": False, "error": f"imap error: {e}"}), 500

    return jsonify({"ok": True, "folder": folder, "count": len(out), "emails": out})


@app.route("/imap/fetch-one", methods=["POST"])
def imap_fetch_one():
    """Fetch full message data (including attachments as base64) for a single UID.

    Body: {"folder": "INBOX", "uid": "12345"}

    Returns the full email with all attachments base64-encoded so n8n can
    save them via /write-base64.
    """
    body = request.get_json(force=True) or {}
    folder = body.get("folder", "INBOX")
    uid = body.get("uid")
    if not uid:
        return jsonify({"ok": False, "error": "uid is required"}), 400

    try:
        with _imap_connect() as mb:
            mb.folder.set(folder)
            msgs = list(mb.fetch(f"UID {uid}", mark_seen=False, bulk=False, limit=1))
            if not msgs:
                return jsonify({"ok": False, "error": "uid not found"}), 404
            msg = msgs[0]
            attachments = []
            for att in msg.attachments:
                attachments.append({
                    "filename": att.filename or "",
                    "mime": att.content_type or "application/octet-stream",
                    "size_bytes": len(att.payload),
                    "base64": base64.b64encode(att.payload).decode("ascii"),
                })
            msg_id = msg.headers.get("message-id", (msg.uid,))[0] if msg.headers.get("message-id") else f"uid:{msg.uid}"
            if msg_id.startswith("<") and msg_id.endswith(">"):
                msg_id = msg_id[1:-1]
            return jsonify({
                "ok": True,
                "uid": msg.uid,
                "message_id": msg_id,
                "subject": msg.subject or "",
                "from_address": msg.from_ or "",
                "from_name": msg.from_values.name if msg.from_values else "",
                "date": msg.date_str or "",
                "body_text": msg.text or "",
                "body_html": msg.html or "",
                "attachments": attachments,
            })
    except Exception as e:
        return jsonify({"ok": False, "error": f"imap error: {e}"}), 500


@app.route("/imap/add-label", methods=["POST"])
def imap_add_label():
    """Apply a Gmail label to a message via IMAP COPY (which Gmail treats as
    'add label' — the original stays in its folder).

    Auto-creates the label if it doesn't exist (handles TRYCREATE response).

    Body: {"source_folder": "INBOX", "uid": "12345", "label": "AI-Tags/Receipts"}
    """
    body = request.get_json(force=True) or {}
    source = body.get("source_folder", "INBOX")
    uid = body.get("uid")
    label = body.get("label")
    if not uid or not label:
        return jsonify({"ok": False, "error": "uid and label required"}), 400

    try:
        with _imap_connect() as mb:
            mb.folder.set(source)
            try:
                mb.copy([str(uid)], label)
            except Exception as copy_err:
                if "TRYCREATE" in str(copy_err):
                    # Label doesn't exist yet — create it and retry
                    mb.folder.create(label)
                    mb.folder.set(source)
                    mb.copy([str(uid)], label)
                else:
                    raise
        return jsonify({"ok": True, "uid": uid, "label_applied": label})
    except Exception as e:
        return jsonify({"ok": False, "error": f"imap error: {e}"}), 500


@app.route("/imap/mark-read", methods=["POST"])
def imap_mark_read():
    """Mark a single message as read.

    Body: {"folder": "INBOX", "uid": "12345"}
    """
    body = request.get_json(force=True) or {}
    folder = body.get("folder", "INBOX")
    uid = body.get("uid")
    if not uid:
        return jsonify({"ok": False, "error": "uid is required"}), 400

    try:
        with _imap_connect() as mb:
            mb.folder.set(folder)
            mb.flag([str(uid)], "\\Seen", True)
        return jsonify({"ok": True, "uid": uid, "marked_read": True})
    except Exception as e:
        return jsonify({"ok": False, "error": f"imap error: {e}"}), 500


@app.route("/imap/archive", methods=["POST"])
def imap_archive():
    """Archive a message (remove from INBOX in Gmail).

    In Gmail's IMAP implementation, archiving = moving to [Gmail]/All Mail.
    The message keeps all its labels but disappears from the Inbox view.

    Body: {"uid": "12345"}
    """
    body = request.get_json(force=True) or {}
    uid = body.get("uid")
    if not uid:
        return jsonify({"ok": False, "error": "uid is required"}), 400

    try:
        with _imap_connect() as mb:
            mb.folder.set("INBOX")
            mb.move([str(uid)], "[Gmail]/All Mail")
        return jsonify({"ok": True, "uid": uid, "archived": True})
    except Exception as e:
        return jsonify({"ok": False, "error": f"imap error: {e}"}), 500


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return {"ok": True, "roots": ALLOWED_ROOTS}




# ---------------------------------------------------------------------------
# List directory contents
# ---------------------------------------------------------------------------
@app.route("/list", methods=["POST"])
def list_dir():
    """List files in a directory. Body: { path: "/files/inbox" }
    Returns: { ok, path, files: [{name, size, modified, is_dir}] }
    """
    try:
        data = request.get_json(force=True)
        dir_path = _resolve(data.get("path", ""))
        if not os.path.isdir(dir_path):
            return jsonify({"ok": False, "error": f"Not a directory: {data.get('path')}"}), 400
        entries = []
        for entry in sorted(os.scandir(dir_path), key=lambda e: e.name):
            stat = entry.stat()
            entries.append({
                "name": entry.name,
                "size": stat.st_size if not entry.is_dir() else None,
                "modified": stat.st_mtime,
                "is_dir": entry.is_dir(),
            })
        return jsonify({"ok": True, "path": data.get("path"), "files": entries})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
