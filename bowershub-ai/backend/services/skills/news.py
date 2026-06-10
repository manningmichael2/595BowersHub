"""Native skill: news headlines from RSS feeds."""

from backend.services.skill_registry import native_skill


@native_skill("news", "headlines", "get-news")
async def handle_news(params: dict) -> dict:
    from backend.services.news import get_news

    return await get_news(
        category=params.get("category"),
        limit=int(params.get("limit", 10)),
    )
