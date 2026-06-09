#!/usr/bin/env python3
"""
Deterministic spec traceability checker for the /spec workflow.

Best-in-class specs are *traceable*: every requirement is implemented by at least
one task, and every task references real requirements. This script enforces that
mechanically (not by LLM judgement), so the /spec workflow can gate "done" on it.

Usage:
    python3 .claude/hooks/spec-validate.py .kiro/specs/<feature>/

Parses requirements.md for `R<n>.<m>` IDs (from `### R1.2 — ...` headers) and
tasks.md for the `R<n>.<m>` IDs referenced on `Requirements:` lines, then reports:
  - requirements with no implementing task   (coverage gap)
  - task references to non-existent requirements (dangling ref)
  - tasks with no Requirements: line at all   (untraced task)

Exit 0 if fully traceable, 1 if any gap (so a caller can branch on it).
"""
import re
import sys
from pathlib import Path

REQ_ID = re.compile(r"R\d+\.\d+")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: spec-validate.py <spec-dir>", file=sys.stderr)
        return 2
    spec_dir = Path(sys.argv[1])
    req_file = spec_dir / "requirements.md"
    task_file = spec_dir / "tasks.md"

    if not req_file.exists() or not task_file.exists():
        print(f"⚠️  Missing requirements.md or tasks.md in {spec_dir}", file=sys.stderr)
        return 2

    # Requirement IDs are defined by `### R1.2 — ...` headers.
    defined = set()
    for line in req_file.read_text().splitlines():
        if line.lstrip().startswith("#"):
            m = re.match(r"#+\s*(R\d+\.\d+)", line.strip())
            if m:
                defined.add(m.group(1))

    # Task references: R-IDs on any line that mentions "Requirements".
    # Also track tasks (## Task ...) and whether each has a Requirements line.
    referenced = set()
    untraced_tasks = []
    current_task = None
    task_has_ref = False
    lines = task_file.read_text().splitlines()

    def close_task():
        if current_task and not task_has_ref:
            untraced_tasks.append(current_task)

    for line in lines:
        if re.match(r"##\s+Task\b", line.strip()):
            close_task()
            current_task = line.strip().lstrip("#").strip()
            task_has_ref = False
        if "requirements" in line.lower() and REQ_ID.search(line):
            for rid in REQ_ID.findall(line):
                referenced.add(rid)
            task_has_ref = True
    close_task()

    uncovered = sorted(defined - referenced, key=_natkey)
    dangling = sorted(referenced - defined, key=_natkey)

    ok = not (uncovered or dangling or untraced_tasks)
    print(f"Spec traceability: {spec_dir}")
    print(f"  requirements defined : {len(defined)}")
    print(f"  requirements covered : {len(defined & referenced)}")
    if uncovered:
        print(f"  ✗ UNCOVERED requirements (no task implements them): {', '.join(uncovered)}")
    if dangling:
        print(f"  ✗ DANGLING task refs (requirement doesn't exist): {', '.join(dangling)}")
    if untraced_tasks:
        print("  ✗ UNTRACED tasks (no Requirements: line):")
        for t in untraced_tasks:
            print(f"      - {t}")
    if ok:
        print("  ✓ fully traceable")
    return 0 if ok else 1


def _natkey(rid: str):
    a, b = rid[1:].split(".")
    return (int(a), int(b))


if __name__ == "__main__":
    sys.exit(main())
