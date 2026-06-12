"""
News headlines skill — fetches current headlines from multiple free RSS sources.

Sources (all free, no API key):
- NPR Top Stories
- ESPN (sports-specific)
- NYT (if accessible)

No authentication needed. Pure RSS parsing.
"""
import logging
from datetime import datetime
from typing import Optional
from xml.etree import ElementTree

import httpx
from backend.http_client import get_http_client

logger = logging.getLogger(__name__)

# RSS feed sources
FEEDS = {
    "top": {
        "url": "https://feeds.npr.org/1001/rss.xml",
        "name": "NPR Top Stories",
    },
    "sports": {
        "url": "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/news?limit=10",
        "name": "ESPN Sports",
        "type": "json",
    },
    "tech": {
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "name": "Ars Technica",
    },
    "world": {
        "url": "https://feeds.npr.org/1004/rss.xml",
        "name": "NPR World",
    },
    "business": {
        "url": "https://feeds.npr.org/1006/rss.xml",
        "name": "NPR Business",
    },
}


async def get_news(category: Optional[str] = None, limit: int = 10) -> dict:
    """
    Fetch current news headlines.

    Args:
        category: One of "top", "sports", "tech", "world", "business".
                  Defaults to "top" if not specified.
        limit: Number of headlines to return (default 10, max 20).
    """
    limit = min(max(limit, 1), 20)

    # Resolve category
    cat = (category or "top").lower().strip()
    if cat not in FEEDS:
        # Try fuzzy match
        for key in FEEDS:
            if cat in key or key in cat:
                cat = key
                break
        else:
            available = ", ".join(FEEDS.keys())
            return {
                "error": f"Unknown news category '{category}'. Available: {available}",
                "_display": f"Unknown news category **{category}**. Try: {available}",
            }

    feed_info = FEEDS[cat]

    try:
        client = get_http_client()
        resp = await client.get(feed_info["url"], headers={"User-Agent": "BowersHub-AI/1.0"}, timeout=10.0)
        resp.raise_for_status()
    except Exception as e:
        return {
            "error": f"Failed to fetch {feed_info['name']}: {e}",
            "_display": f"⚠️ Could not reach {feed_info['name']}. Try again shortly.",
        }

    # Parse based on feed type
    if feed_info.get("type") == "json":
        headlines = _parse_espn_json(resp.text, limit)
    else:
        headlines = _parse_rss(resp.text, limit)

    if not headlines:
        return {
            "source": feed_info["name"],
            "headlines": [],
            "_display": f"No headlines available from {feed_info['name']} right now.",
        }

    display = _render_headlines(feed_info["name"], headlines)
    return {
        "source": feed_info["name"],
        "category": cat,
        "count": len(headlines),
        "headlines": headlines,
        "_display": display,
    }


def _parse_rss(xml_text: str, limit: int) -> list[dict]:
    """Parse RSS XML into headline dicts."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as e:
        logger.warning(f"RSS parse error: {e}")
        return []

    items = root.findall(".//channel/item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    headlines = []

    for item in items[:limit]:
        title_el = item.find("title")
        desc_el = item.find("description")
        pub_el = item.find("pubDate")
        link_el = item.find("link")

        if title_el is None or not title_el.text:
            continue

        headline = {"title": title_el.text.strip()}
        if desc_el is not None and desc_el.text:
            # Strip HTML tags from description
            desc = desc_el.text.strip()
            # Simple tag stripping
            import re
            desc = re.sub(r"<[^>]+>", "", desc)
            if len(desc) > 200:
                desc = desc[:197] + "..."
            headline["summary"] = desc
        if pub_el is not None and pub_el.text:
            headline["published"] = _parse_date(pub_el.text.strip())
        if link_el is not None:
            headline["url"] = link_el.text.strip() if link_el.text else (link_el.get("href") or "")

        headlines.append(headline)

    return headlines


def _parse_espn_json(text: str, limit: int) -> list[dict]:
    """Parse ESPN's JSON news format."""
    import json
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []

    articles = data.get("articles", [])
    headlines = []

    for article in articles[:limit]:
        headline = {"title": article.get("headline", "")}
        if article.get("description"):
            desc = article["description"]
            if len(desc) > 200:
                desc = desc[:197] + "..."
            headline["summary"] = desc
        if article.get("published"):
            headline["published"] = article["published"][:10]
        if article.get("links", {}).get("web", {}).get("href"):
            headline["url"] = article["links"]["web"]["href"]
        headlines.append(headline)

    return headlines


def _parse_date(date_str: str) -> str:
    """Parse various date formats into a readable string."""
    # Try common RSS date formats
    for fmt in [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ]:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%b %-d")
        except ValueError:
            continue
    # Fallback: return first 10 chars
    return date_str[:10]


def _render_headlines(source_name: str, headlines: list[dict]) -> str:
    """Render headlines as clean markdown."""
    lines = [f"## 📰 {source_name}", ""]

    for h in headlines:
        title = h.get("title", "")
        summary = h.get("summary", "")
        published = h.get("published", "")

        date_str = f" *({published})*" if published else ""
        lines.append(f"- **{title}**{date_str}")
        if summary:
            lines.append(f"  {summary}")

    return "\n".join(lines)
