"""
Unit tests for the briefing summary parser.

Validates `backend.services.briefing_summary.parse_sections` behavior:
- Returns the five canonical sections (weather, yesterday_spending, inbox,
  schedule, anything_else) in fixed order regardless of input order.
- Detects sections by the `**<Label>:**` heading pattern emitted by
  `backend.services.briefing.BriefingService`.
- Substitutes the `—` placeholder for any section the briefing omitted or
  that has empty content (R8.7).
- Tolerates malformed / unstructured markdown without raising.

Validates: Requirements R8.2, R8.7
"""

from __future__ import annotations

from backend.services.briefing_summary import (
    EXPECTED_SECTIONS,
    MISSING_PLACEHOLDER,
    parse_sections,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CANONICAL_KEYS = ["weather", "yesterday_spending", "inbox", "schedule", "anything_else", "finance_insights"]
CANONICAL_LABELS = [
    "Weather",
    "Yesterday's Spending",
    "Inbox",
    "Today's Schedule",
    "Anything Else",
    "Finance Insights",
]


def _by_key(sections):
    return {s["key"]: s for s in sections}


# ---------------------------------------------------------------------------
# Shape / canonical order
# ---------------------------------------------------------------------------

def test_expected_sections_constant_matches_canonical_order():
    """Sanity: the module's EXPECTED_SECTIONS matches the spec'd canonical order."""
    assert [k for k, _ in EXPECTED_SECTIONS] == CANONICAL_KEYS
    assert [lbl for _, lbl in EXPECTED_SECTIONS] == CANONICAL_LABELS


def test_returns_five_sections_in_canonical_order_regardless_of_input_order():
    """Even when the briefing emits sections out of order, output order is fixed."""
    markdown = (
        "**Anything Else:**\nrandom note\n\n"
        "**Inbox:**\n3 files\n\n"
        "**Weather:**\nSunny 72\n\n"
        "**Today's Schedule:**\nNothing on the calendar\n\n"
        "**Yesterday's Spending:**\n$42.00\n"
    )
    sections = parse_sections(markdown)
    assert [s["key"] for s in sections] == CANONICAL_KEYS
    assert [s["label"] for s in sections] == CANONICAL_LABELS


# ---------------------------------------------------------------------------
# Full briefing — all five sections present
# ---------------------------------------------------------------------------

def test_full_briefing_with_all_sections():
    """A briefing containing all five sections returns each parsed section's content."""
    markdown = (
        "Good morning!\n\n"
        "**Weather:**\nSunny 72°F humidity 40%\n\n"
        "**Yesterday's Spending:**\n$84.12 across 5 transactions\n\n"
        "**Inbox:**\n7 files (3 images)\n\n"
        "**Today's Schedule:**\n- 10am standup\n- 2pm dentist\n\n"
        "**Anything Else:**\nDon't forget the package on the porch.\n\n"
        "**Finance Insights:**\n- Netflix rose to $15.00 from $10.00\n"
    )
    by_key = _by_key(parse_sections(markdown))

    assert by_key["weather"]["content"] == "Sunny 72°F humidity 40%"
    assert by_key["yesterday_spending"]["content"] == "$84.12 across 5 transactions"
    assert by_key["inbox"]["content"] == "7 files (3 images)"
    assert by_key["schedule"]["content"] == "- 10am standup\n- 2pm dentist"
    assert by_key["anything_else"]["content"] == "Don't forget the package on the porch."
    assert by_key["finance_insights"]["content"] == "- Netflix rose to $15.00 from $10.00"

    # No placeholders when every section is present and non-empty.
    for section in by_key.values():
        assert section["content"] != MISSING_PLACEHOLDER


def test_section_labels_match_canonical_labels():
    """Every returned section's label matches the canonical label for its key."""
    markdown = "**Weather:**\nClear\n\n**Inbox:**\n2 files\n"
    by_key = _by_key(parse_sections(markdown))
    for key, label in EXPECTED_SECTIONS:
        assert by_key[key]["label"] == label


# ---------------------------------------------------------------------------
# Missing sections — single and multiple
# ---------------------------------------------------------------------------

def test_briefing_missing_weather_uses_placeholder_for_weather_only():
    """When the weather section is omitted, only weather gets the `—` placeholder."""
    markdown = (
        "**Yesterday's Spending:**\n$10.00 across 1 transaction\n\n"
        "**Inbox:**\n0 files\n\n"
        "**Today's Schedule:**\nFree day\n\n"
        "**Anything Else:**\nNothing notable.\n"
    )
    by_key = _by_key(parse_sections(markdown))

    assert by_key["weather"]["content"] == MISSING_PLACEHOLDER
    assert by_key["weather"]["label"] == "Weather"

    # The other four sections are populated with their real content.
    assert by_key["yesterday_spending"]["content"] == "$10.00 across 1 transaction"
    assert by_key["inbox"]["content"] == "0 files"
    assert by_key["schedule"]["content"] == "Free day"
    assert by_key["anything_else"]["content"] == "Nothing notable."


def test_briefing_missing_multiple_sections_uses_placeholder_for_each():
    """Multiple omitted sections all return the placeholder; present sections survive."""
    markdown = (
        "**Weather:**\nCloudy 60°F\n\n"
        "**Inbox:**\n12 files\n"
    )
    by_key = _by_key(parse_sections(markdown))

    assert by_key["weather"]["content"] == "Cloudy 60°F"
    assert by_key["inbox"]["content"] == "12 files"

    # Three missing sections — all placeholders, still in canonical order.
    assert by_key["yesterday_spending"]["content"] == MISSING_PLACEHOLDER
    assert by_key["schedule"]["content"] == MISSING_PLACEHOLDER
    assert by_key["anything_else"]["content"] == MISSING_PLACEHOLDER


def test_section_with_empty_content_uses_placeholder():
    """A section whose body is whitespace-only is treated as missing."""
    markdown = (
        "**Weather:**\n   \n\n"
        "**Inbox:**\n5 files\n"
    )
    by_key = _by_key(parse_sections(markdown))
    assert by_key["weather"]["content"] == MISSING_PLACEHOLDER
    assert by_key["inbox"]["content"] == "5 files"


# ---------------------------------------------------------------------------
# Malformed / unstructured markdown
# ---------------------------------------------------------------------------

def test_malformed_markdown_returns_all_placeholders():
    """Markdown with no recognized headings yields a placeholder for every section."""
    markdown = (
        "This is just unstructured prose with no headings at all.\n"
        "It might contain words like Weather or Inbox in body text but not as headings.\n"
        "Random *italic* and **bold without colon** content here.\n"
    )
    sections = parse_sections(markdown)
    assert [s["key"] for s in sections] == CANONICAL_KEYS
    for s in sections:
        assert s["content"] == MISSING_PLACEHOLDER


def test_empty_string_returns_all_placeholders():
    """Empty input yields the canonical five sections, all with placeholders."""
    sections = parse_sections("")
    assert [s["key"] for s in sections] == CANONICAL_KEYS
    for s in sections:
        assert s["content"] == MISSING_PLACEHOLDER


def test_non_string_input_returns_all_placeholders():
    """Defensive: non-string input does not raise; returns canonical placeholders."""
    sections = parse_sections(None)  # type: ignore[arg-type]
    assert [s["key"] for s in sections] == CANONICAL_KEYS
    for s in sections:
        assert s["content"] == MISSING_PLACEHOLDER


def test_heading_without_bold_markers_is_not_recognized():
    """A line like `Weather:` (no `**`) should not be parsed as a section heading."""
    markdown = (
        "Weather: Sunny 72\n"
        "Inbox: 3 files\n"
    )
    sections = parse_sections(markdown)
    # No `**Label:**` patterns means every section is missing.
    for s in sections:
        assert s["content"] == MISSING_PLACEHOLDER


def test_duplicate_section_heading_keeps_first_occurrence():
    """If a label appears twice, the first occurrence wins (deterministic)."""
    markdown = (
        "**Weather:**\nFirst body\n\n"
        "**Weather:**\nSecond body\n"
    )
    by_key = _by_key(parse_sections(markdown))
    assert by_key["weather"]["content"] == "First body"
