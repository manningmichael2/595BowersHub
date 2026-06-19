"""
Normalization utility: handles AI synonym mapping and canonical parameter names.
Ensures consistency across all skills.
"""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Synonym maps are scoped PER SKILL. A global map is a foot-gun: a generic key
# like "id" or "content" means different things to different skills, so rewriting
# it everywhere can clobber legitimate params on unrelated skills.
#
# _UNIVERSAL holds only mappings that are unambiguous across every skill.
_UNIVERSAL = {
    "amount_min": "min_amount",
    "amount_max": "max_amount",
}

# Per-skill synonym maps: the model frequently invents these keys.
_CATEGORIZE_MERCHANT_SYNONYMS = {
    "merchant": "description_pattern",
    "merchant_name": "description_pattern",
    "pattern": "description_pattern",
    "category": "category_name",
}
_SKILL_SYNONYMS: Dict[str, Dict[str, str]] = {
    "categorize-merchant": _CATEGORIZE_MERCHANT_SYNONYMS,
    "commit-bulk-update": _CATEGORIZE_MERCHANT_SYNONYMS,
    "categorize-transaction": {
        "id": "transaction_id",
        "txn_id": "transaction_id",
        "category": "category_name",
    },
}


def normalize_skill_params(skill_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize parameter names for a specific skill.
    Maps known synonyms (universal + skill-scoped) to canonical backend names.
    """
    if not isinstance(params, dict):
        return {}

    skill_map = _SKILL_SYNONYMS.get(skill_name, {})

    normalized: Dict[str, Any] = {}
    for key, value in params.items():
        lk = key.lower()
        canonical_key = skill_map.get(lk) or _UNIVERSAL.get(lk) or key
        # Don't let a synonym overwrite a value the model already passed canonically.
        if canonical_key in normalized and canonical_key != key:
            continue
        normalized[canonical_key] = value

    # ask-db accepts either 'question' (legacy) or 'query' — keep both populated.
    if skill_name == "ask-db":
        if "query" in normalized and "question" not in normalized:
            normalized["question"] = normalized["query"]
        elif "question" in normalized and "query" not in normalized:
            normalized["query"] = normalized["question"]

    return normalized


async def lookup_category_alias(conn, alias: str) -> str:
    """
    Lookup a natural language alias in the DB.
    Returns the canonical category name if found, else the original string.
    """
    if not alias:
        return alias
        
    row = await conn.fetchrow(
        "SELECT c.name FROM finance.category_aliases a "
        "JOIN finance.categories c ON c.id = a.category_id "
        "WHERE LOWER(a.alias) = LOWER($1)",
        alias.strip()
    )
    if row:
        return row["name"]
    return alias
