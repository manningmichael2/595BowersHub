#!/usr/bin/env python3
"""
PostToolUse hook for the 595BowersHub project.

Mirrors Kiro's `fileEdited` hook: when Claude Code writes or edits a file under
`.kiro/specs/`, emit a short confirmation so spec changes are visible in the
transcript. No-ops silently for every other file, so it's cheap to run on every
Write/Edit.

Claude Code passes the tool event as JSON on stdin (fields include `tool_name`
and `tool_input.file_path`). This script reads that, filters for spec files, and
exits 0 regardless (a hook must never block normal edits).
"""
import json
import sys


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0  # malformed / empty input — do nothing

    tool_input = data.get("tool_input") or {}
    path = (
        tool_input.get("file_path")
        or tool_input.get("path")
        or ""
    )
    if ".kiro/specs/" in path:
        name = path.split(".kiro/specs/", 1)[1]
        print(f"📋 Spec updated: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
