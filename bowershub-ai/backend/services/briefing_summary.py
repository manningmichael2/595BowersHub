"""
Briefing summary parser: pure markdown sectioner.

Extracts the five expected sections from briefing markdown produced by
`BriefingService.generate()`. Sections are detected by the `**<Label>:**`
heading pattern as emitted by `briefing.py`.

For any expected section that the briefing omits, returns the section with
content `"—"` (R8.7).

Pure functions, no I/O.
"""

from __future__ import annotations

import re
from typing import List, TypedDict

# Canonical order and slug keys for the five expected sections.
# Order matches Requirement 8.2 (weather, spending, inbox, schedule, anything-else).
EXPECTED_SECTIONS: List[tuple[str, str]] = [
    ("weather", "Weather"),
    ("yesterday_spending", "Yesterday's Spending"),
    ("inbox", "Inbox"),
    ("schedule", "Today's Schedule"),
    ("anything_else", "Anything Else"),
]

# Placeholder used when a section is missing or empty (R8.7).
MISSING_PLACEHOLDER = "—"


class Section(TypedDict):
    key: str
    label: str
    content: str


def parse_sections(markdown: str) -> List[Section]:
    """
    Extract the five expected sections from briefing markdown.

    Sections are detected by the `**<Label>:**` heading pattern. Content for a
    section runs from the end of its heading until the next recognized heading
    or end of input. Whitespace around content is trimmed.

    Any expected section that the briefing omitted (or that has empty content
    after trimming) is returned with content = "—".

    Returns sections in canonical order regardless of order they appear in the
    markdown.
    """
    if not isinstance(markdown, str) or not markdown:
        return [
            {"key": key, "label": label, "content": MISSING_PLACEHOLDER}
            for key, label in EXPECTED_SECTIONS
        ]

    # Build a regex alternation of the expected labels. Escape labels so chars
    # like the apostrophe in "Yesterday's Spending" are matched literally.
    # Pattern matches a `**Label:**` heading; capture the label.
    label_alternation = "|".join(re.escape(label) for _, label in EXPECTED_SECTIONS)
    heading_re = re.compile(rf"\*\*({label_alternation}):\*\*")

    # Map label -> key for quick lookup.
    label_to_key = {label: key for key, label in EXPECTED_SECTIONS}

    # Find all heading matches in document order.
    matches = list(heading_re.finditer(markdown))

    # Extract content: from end of match N to start of match N+1 (or end of string).
    found: dict[str, str] = {}
    for i, m in enumerate(matches):
        label = m.group(1)
        key = label_to_key[label]
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        content = markdown[start:end].strip()
        if not content:
            content = MISSING_PLACEHOLDER
        # If a label appears more than once, keep the first occurrence.
        found.setdefault(key, content)

    return [
        {
            "key": key,
            "label": label,
            "content": found.get(key, MISSING_PLACEHOLDER),
        }
        for key, label in EXPECTED_SECTIONS
    ]
