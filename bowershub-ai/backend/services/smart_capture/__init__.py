"""Native smart-capture (n8n-decommission spec).

Ports the n8n `Smart Capture` workflow (extract → per-intent commit) in-process,
behind a DB-driven engine switch (`smart_capture.engine` = n8n|native|shadow).
See `.kiro/specs/n8n-decommission/design.md`.

Modules:
  config.py   — DB-driven engine + token secret + gates (bh_platform_settings).
  intents.py  — typed CaptureIntent + the single canonical()/hash() form.
  tokens.py   — real HMAC-SHA256 extract tokens (mint/verify, membership).
  prompt.py   — the ported classify prompt + DOMAINS allow-list (Task 3).
  extract.py  — extract_native (Task 3).
  commit.py   — commit_native + committers (Task 4).
  engine.py   — run_extract/run_commit engine branch (Task 5).
"""
