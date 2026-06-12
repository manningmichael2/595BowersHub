"""
Email Manager — fetches, classifies, and optionally cleans inbox emails.

Uses Llama 3.2 3B (via Ollama) to classify emails into categories.
Zero API cost for classification.

Commands:
- `/email` — show most important recent emails (digest view)
- `/email clean` — classify and archive junk/newsletters/marketing
- `/email preview` — dry-run of clean (show what would happen)
- `/email all` — show all recent emails with categories

Triggered via:
- On-demand via `/email` slash command
- Scheduled nightly cleanup via apscheduler
"""
import logging
from backend.services.model_catalog import resolve_role
import os
from typing import Any, Dict, List

import httpx
from backend.http_client import get_http_client

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
FILEWRITER_URL = os.environ.get("FILEWRITER_URL", "http://filewriter:5001")

# Email categories and their actions
CATEGORIES = {
    "important": {"action": "keep", "label": None, "description": "Personal, work, or action-required emails"},
    "newsletter": {"action": "archive", "label": "AI-Tags/Newsletter", "description": "Newsletter or blog subscriptions"},
    "marketing": {"action": "archive", "label": "AI-Tags/Marketing", "description": "Promotional emails, deals, sales"},
    "receipt": {"action": "label", "label": "AI-Tags/Receipts", "description": "Purchase confirmations, invoices"},
    "shipping": {"action": "label", "label": "AI-Tags/Shipping", "description": "Delivery notifications, tracking updates"},
    "social": {"action": "archive", "label": "AI-Tags/Social", "description": "Social media notifications"},
    "spam": {"action": "archive", "label": "AI-Tags/Spam", "description": "Unwanted commercial email"},
    "keep": {"action": "keep", "label": None, "description": "Unsure — leave in inbox"},
}

CLASSIFICATION_PROMPT = """You classify emails into one category. Given the sender, subject, and first few lines of an email, respond with ONLY the category name (one word, lowercase).

Categories:
- important: Personal messages, work emails, account security, legal, medical, financial alerts
- newsletter: Subscribed newsletters, blog digests, weekly roundups
- marketing: Promotions, deals, "limited time offer", store emails
- receipt: Purchase confirmations, order receipts, payment confirmations, invoices
- shipping: Package tracking, delivery updates, "your order has shipped"
- social: Social media notifications (Facebook, LinkedIn, Twitter, etc.)
- spam: Unsolicited commercial email, scams
- keep: Anything you're unsure about

Email:
From: {sender}
Subject: {subject}
Preview: {preview}

Category:"""


async def classify_email(sender: str, subject: str, preview: str) -> str:
    """Classify a single email using Ollama (local model, free)."""
    prompt = CLASSIFICATION_PROMPT.format(
        sender=sender[:100],
        subject=subject[:200],
        preview=preview[:300],
    )

    try:
        client = get_http_client()
        resp = await client.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": resolve_role("local"),
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 10},
            },
        )
        resp.raise_for_status()
        result = resp.json().get("response", "").strip().lower()

        # Normalize — take first word only
        category = result.split()[0].rstrip(".,;:") if result else "keep"
        if category not in CATEGORIES:
            category = "keep"
        return category

    except Exception as e:
        logger.warning(f"Ollama classification failed: {e}")
        return "keep"  # Safe fallback


async def fetch_recent_emails(count: int = 30, unseen_only: bool = True) -> List[Dict[str, Any]]:
    """Fetch recent emails from inbox via filewriter IMAP (POST endpoint)."""
    try:
        client = get_http_client()
        resp = await client.post(
            f"{FILEWRITER_URL}/imap/fetch-recent",
            json={
                "folder": "INBOX",
                "since_minutes": 1440,  # Last 24 hours
                "limit": count,
                "include_body": True,
                "body_max_chars": 500,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            logger.error(f"IMAP fetch failed: {data.get('error', 'unknown')}")
            return []
        # Normalize field names to what our classifier expects
        emails = []
        for em in data.get("emails", []):
            emails.append({
                "uid": em.get("uid", ""),
                "from": f"{em.get('from_name', '')} <{em.get('from_address', '')}>".strip(),
                "from_name": em.get("from_name", ""),
                "from_address": em.get("from_address", ""),
                "subject": em.get("subject", ""),
                "preview": em.get("body_text", "")[:300],
                "date": em.get("date", ""),
            })
        return emails
    except Exception as e:
        logger.error(f"Failed to fetch emails: {e}")
        return []


async def apply_label(uid: str, label: str) -> bool:
    """Apply a Gmail label to an email via filewriter."""
    try:
        client = get_http_client()
        resp = await client.post(
            f"{FILEWRITER_URL}/imap/add-label",
            json={"uid": uid, "label": label},
        )
        return resp.status_code == 200
    except Exception:
        return False


async def archive_email(uid: str) -> bool:
    """Archive an email (remove from INBOX) via filewriter."""
    try:
        client = get_http_client()
        resp = await client.post(
            f"{FILEWRITER_URL}/imap/mark-read",
            json={"uid": uid, "archive": True},
        )
        return resp.status_code == 200
    except Exception:
        return False


async def email_digest(limit: int = 20) -> dict:
    """
    Show a prioritized digest of recent emails — important ones first,
    with a summary of what else is there.
    
    This is the default `/email` mode. Read-only, no actions taken.
    """
    emails = await fetch_recent_emails(count=limit, unseen_only=True)

    if not emails:
        return {
            "processed": 0,
            "_display": "📭 No unread emails in your inbox.",
        }

    # Classify all emails
    classified = []
    for email in emails:
        sender = email.get("from", "")
        sender_name = email.get("from_name", "") or _short_sender(sender)
        subject = email.get("subject", "")
        preview = email.get("preview", "")[:300]
        uid = email.get("uid", "")
        date = email.get("date", "")

        category = await classify_email(sender, subject, preview)
        classified.append({
            "uid": uid,
            "from": sender,
            "from_short": sender_name or _short_sender(sender),
            "subject": subject,
            "preview": preview[:120],
            "date": date,
            "category": category,
        })

    # Split into priority groups
    important = [e for e in classified if e["category"] in ("important", "keep")]
    receipts = [e for e in classified if e["category"] == "receipt"]
    shipping = [e for e in classified if e["category"] == "shipping"]
    noise = [e for e in classified if e["category"] in ("newsletter", "marketing", "social", "spam")]

    # Build display — show what matters
    lines = [f"**📬 Email** ({len(emails)} unread)\n"]

    if important:
        lines.append("**Priority:**")
        for e in important:
            lines.append(f"- **{e['from_short']}** — {e['subject'][:60]}")
            if e["preview"]:
                lines.append(f"  _{e['preview'][:80]}..._")
        lines.append("")

    if receipts:
        lines.append("**🧾 Receipts:**")
        for e in receipts:
            lines.append(f"- {e['from_short']} — {e['subject'][:60]}")
        lines.append("")

    if shipping:
        lines.append("**📦 Shipping:**")
        for e in shipping:
            lines.append(f"- {e['from_short']} — {e['subject'][:60]}")
        lines.append("")

    if noise:
        # Just a summary line for the junk
        breakdown = []
        newsletters = [e for e in noise if e["category"] == "newsletter"]
        marketing = [e for e in noise if e["category"] == "marketing"]
        social = [e for e in noise if e["category"] == "social"]
        spam = [e for e in noise if e["category"] == "spam"]
        if newsletters:
            breakdown.append(f"{len(newsletters)} newsletters")
        if marketing:
            breakdown.append(f"{len(marketing)} marketing")
        if social:
            breakdown.append(f"{len(social)} social")
        if spam:
            breakdown.append(f"{len(spam)} spam")
        lines.append(f"**Filtered:** {', '.join(breakdown)}")
        lines.append(f"_Use `/email clean` to archive these._")

    return {
        "processed": len(classified),
        "important": len(important),
        "noise": len(noise),
        "_display": "\n".join(lines),
    }


async def email_all(limit: int = 30) -> dict:
    """Show all recent emails with their categories — no actions taken."""
    emails = await fetch_recent_emails(count=limit, unseen_only=True)

    if not emails:
        return {
            "processed": 0,
            "_display": "📭 No unread emails in your inbox.",
        }

    classified = []
    for email in emails:
        sender = email.get("from", "")
        sender_name = email.get("from_name", "") or _short_sender(sender)
        subject = email.get("subject", "")
        preview = email.get("preview", "")[:300]
        category = await classify_email(sender, subject, preview)
        classified.append({
            "from": sender_name,
            "subject": subject[:50],
            "category": category,
        })

    lines = [f"**📬 All Emails** ({len(classified)} unread)\n"]
    for e in classified:
        emoji = {"important": "⭐", "newsletter": "📰", "marketing": "📢",
                 "receipt": "🧾", "shipping": "📦", "social": "💬",
                 "spam": "🚫", "keep": "📌"}.get(e["category"], "•")
        lines.append(f"- {emoji} **{e['from']}** — {e['subject']} _({e['category']})_")

    return {
        "processed": len(classified),
        "_display": "\n".join(lines),
    }


async def clean_inbox(limit: int = 30, dry_run: bool = False) -> dict:
    """
    Classify emails and archive the noise.
    
    Args:
        limit: Max emails to process
        dry_run: If True, classify but don't apply actions (preview mode)
    
    Returns:
        Summary dict with counts and details.
    """
    emails = await fetch_recent_emails(count=limit, unseen_only=True)

    if not emails:
        return {
            "processed": 0,
            "_display": "📭 No unread emails to process.",
        }

    results = []
    counts = {cat: 0 for cat in CATEGORIES}

    for email in emails:
        sender = email.get("from", "")
        sender_name = email.get("from_name", "") or _short_sender(sender)
        subject = email.get("subject", "")
        preview = email.get("preview", "")[:300]
        uid = email.get("uid", "")

        category = await classify_email(sender, subject, preview)
        counts[category] += 1

        action_info = CATEGORIES[category]
        result_entry = {
            "uid": uid,
            "from": sender_name,
            "subject": subject[:80],
            "category": category,
            "action": action_info["action"],
        }

        if not dry_run and uid:
            # Apply label if specified
            if action_info["label"]:
                await apply_label(uid, action_info["label"])
            # Archive if action is "archive"
            if action_info["action"] == "archive":
                await archive_email(uid)

        results.append(result_entry)

    # Build display
    archived = [r for r in results if r["action"] == "archive"]
    kept = [r for r in results if r["action"] == "keep"]
    labeled = [r for r in results if r["action"] == "label"]

    lines = []
    if dry_run:
        lines.append(f"**📬 Email Cleanup Preview** ({len(results)} emails)\n")
        lines.append("*No actions taken — showing what would happen:*\n")
    else:
        lines.append(f"**📬 Email Cleanup** ({len(results)} emails processed)\n")

    # Summary counts
    for cat, count in sorted(counts.items(), key=lambda x: -x[1]):
        if count > 0:
            emoji = {"important": "⭐", "newsletter": "📰", "marketing": "📢",
                     "receipt": "🧾", "shipping": "📦", "social": "💬",
                     "spam": "🚫", "keep": "📌"}.get(cat, "•")
            action = CATEGORIES[cat]["action"]
            lines.append(f"- {emoji} **{cat}**: {count} ({action})")

    lines.append("")

    if not dry_run:
        if archived:
            lines.append(f"✅ **Archived {len(archived)}** (newsletters, marketing, social, spam)")
        if labeled:
            lines.append(f"🏷️ **Labeled {len(labeled)}** (receipts, shipping)")
        if kept:
            lines.append(f"📌 **Kept {len(kept)}** in inbox")
    else:
        if archived:
            lines.append(f"Would archive: {len(archived)}")
        if labeled:
            lines.append(f"Would label: {len(labeled)}")
        if kept:
            lines.append(f"Would keep: {len(kept)}")

    # Details list
    if results:
        lines.append("\n**Details:**")
        for r in results[:15]:
            emoji = {"important": "⭐", "newsletter": "📰", "marketing": "📢",
                     "receipt": "🧾", "shipping": "📦", "social": "💬",
                     "spam": "🚫", "keep": "📌"}.get(r["category"], "•")
            lines.append(f"- {emoji} **{r['from']}** — {r['subject'][:50]} → _{r['action']}_")
        if len(results) > 15:
            lines.append(f"- _...+{len(results) - 15} more_")

    return {
        "processed": len(results),
        "counts": counts,
        "archived": len(archived),
        "kept": len(kept),
        "labeled": len(labeled),
        "results": results,
        "_display": "\n".join(lines),
    }


async def email_unsubscribe(limit: int = 50) -> dict:
    """
    Find senders that consistently get classified as marketing/newsletter/spam
    and show their emails with List-Unsubscribe info (if available).
    
    Fetches recent emails, classifies them, and groups noise senders
    so the user can decide which to unsubscribe from.
    """
    emails = await fetch_recent_emails(count=limit, unseen_only=False)

    if not emails:
        return {
            "processed": 0,
            "_display": "📭 No emails to analyze for unsubscribe candidates.",
        }

    # Classify and group by sender
    sender_categories: dict = {}  # sender_address -> list of categories
    sender_subjects: dict = {}    # sender_address -> list of subjects
    sender_names: dict = {}       # sender_address -> display name

    for email in emails:
        sender = email.get("from", "")
        sender_name = email.get("from_name", "") or _short_sender(sender)
        sender_addr = email.get("from_address", "") or sender
        subject = email.get("subject", "")
        preview = email.get("preview", "")[:300]

        category = await classify_email(sender, subject, preview)

        if sender_addr not in sender_categories:
            sender_categories[sender_addr] = []
            sender_subjects[sender_addr] = []
            sender_names[sender_addr] = sender_name

        sender_categories[sender_addr].append(category)
        sender_subjects[sender_addr].append(subject[:50])

    # Find senders that are consistently noise (all their emails = marketing/newsletter/spam/social)
    noise_categories = {"marketing", "newsletter", "spam", "social"}
    unsubscribe_candidates = []

    for addr, categories in sender_categories.items():
        if all(c in noise_categories for c in categories) and len(categories) >= 1:
            unsubscribe_candidates.append({
                "address": addr,
                "name": sender_names[addr],
                "count": len(categories),
                "categories": list(set(categories)),
                "subjects": sender_subjects[addr][:3],
            })

    # Sort by volume (most emails first)
    unsubscribe_candidates.sort(key=lambda x: -x["count"])

    if not unsubscribe_candidates:
        return {
            "processed": len(emails),
            "_display": "✅ No obvious unsubscribe candidates found. Your inbox is clean!",
        }

    lines = [f"**📧 Unsubscribe Candidates** ({len(unsubscribe_candidates)} senders)\n"]
    lines.append("_These senders consistently send marketing, newsletters, or spam:_\n")

    for cand in unsubscribe_candidates[:15]:
        emoji = "📰" if "newsletter" in cand["categories"] else "📢"
        lines.append(f"- {emoji} **{cand['name']}** ({cand['address']})")
        lines.append(f"  {cand['count']} email{'s' if cand['count'] > 1 else ''} — {', '.join(cand['categories'])}")
        if cand["subjects"]:
            lines.append(f"  _Latest: {cand['subjects'][0]}_")

    lines.append("\n_To unsubscribe: open these emails in Gmail and look for the 'Unsubscribe' link at the top, or scroll to the bottom of the email._")
    lines.append("_Use `/email clean` to archive all current junk._")

    return {
        "processed": len(emails),
        "candidates": len(unsubscribe_candidates),
        "_display": "\n".join(lines),
    }


def _short_sender(sender: str) -> str:
    """Extract a readable name from an email 'From' header.
    
    'Michael Manning <manningmichael2@gmail.com>' → 'Michael Manning'
    'noreply@amazon.com' → 'noreply@amazon.com'
    """
    if "<" in sender:
        name = sender.split("<")[0].strip().strip('"').strip("'")
        if name:
            return name
    return sender[:40]
