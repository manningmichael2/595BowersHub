#!/usr/bin/env bash
#
# sync-public.sh — publish a scrubbed, app-only snapshot of this PRIVATE repo
# into the PUBLIC `private-ai-hub` repo.
#
# Model: the private repo (595BowersHub) is the source of truth. The public repo
# has its OWN history — each run makes ONE "sync: <label>" commit. We never share
# git lineage (the private history carries a personal email, real name, and the
# address-based repo name, none of which can be scrubbed from history without a
# disruptive rewrite). So this is a snapshot mirror, not a fork.
#
# What it does, in order:
#   1. Stage an app-only include set into a temp tree.
#   2. Scrub every personal identifier (email / Tailscale IP / home path / the
#      household first names) via deterministic replacements.
#   3. VERIFY — hard-fail if any identifier survives the scrub.
#   4. Mirror the staged tree into the public repo working tree (preserving .git)
#      and make a single snapshot commit.
#
# It does NOT create or push a GitHub repo — that outward-facing step is left to
# you (see the printed next-steps). Review the staged result first.
#
# Usage:
#   scripts/sync-public.sh "sync: screenshots epic"
#   PUBLIC_REPO_DIR=/path/to/private-ai-hub scripts/sync-public.sh "..."
#
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PUB="${PUBLIC_REPO_DIR:-$HOME/private-ai-hub}"
LABEL="${1:-snapshot $(date +%Y-%m-%d)}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "▸ private (source): $SRC"
echo "▸ public (target):  $PUB"
echo "▸ snapshot label:   $LABEL"
echo

# ── 1. Stage the app-only include set ──────────────────────────────────────────
# The app + the public-facing README + the demo screenshots + a LICENSE. Nothing
# else (no journals, steering, home-lab services, live schema, archive).
mkdir -p "$STAGE/bowershub-ai" "$STAGE/docs"

rsync -a \
  --exclude '.pytest_cache/' \
  --exclude '__pycache__/' \
  --exclude 'node_modules/' \
  --exclude 'dist/' \
  --exclude '.venv/' \
  --exclude 'static/' \
  --exclude 'backend/migrations/_archive/' \
  --exclude 'SYSTEM_REVIEW_2026-06-07.md' \
  --exclude 'docs/' \
  --exclude 'deploy.sh' \
  --exclude 'scripts/' \
  "$SRC/bowershub-ai/" "$STAGE/bowershub-ai/"

# scripts/ is one-off ops tooling with real merchant/person names and the server
# hostname — excluded wholesale EXCEPT generate_icons.py, which the Dockerfile
# copies at build time.
mkdir -p "$STAGE/bowershub-ai/scripts"
cp "$SRC/bowershub-ai/scripts/generate_icons.py" "$STAGE/bowershub-ai/scripts/generate_icons.py"

cp "$SRC/README.md" "$STAGE/README.md"
rsync -a "$SRC/docs/screenshots/" "$STAGE/docs/screenshots/"

# A neutral MIT license (holder is intentionally not a personal name — change it
# if you want attribution).
cat > "$STAGE/LICENSE" <<'LICENSE'
MIT License

Copyright (c) 2026 private-ai-hub contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
LICENSE

cat > "$STAGE/.gitignore" <<'GITIGNORE'
# Secrets — never commit
.env
*.env
!.env.example
# Python
__pycache__/
*.pyc
.venv/
venv/
.pytest_cache/
# Node / build
node_modules/
dist/
static/
GITIGNORE

# ── 2 + 3. Scrub identifiers, then VERIFY (hard-fail on any survivor) ───────────
python3 - "$STAGE" <<'PY'
import os, re, sys

root = sys.argv[1]

# (pattern, replacement). ORDER MATTERS — compound strings (FQDN, email, home
# path) are replaced before the bare tokens they contain, so a later rule can't
# mangle a substring of an already-handled value.
REPLACEMENTS = [
    # Address + network identity (most specific first)
    (re.compile(r'595bowershub\.tailc4d58a\.ts\.net'), 'homehub.example.ts.net'),
    (re.compile(r'tailc4d58a'),                        'example'),
    (re.compile(r'595BowersHub'),                      'HomeHub'),
    (re.compile(r'595bowershub'),                       'homehub'),
    (re.compile(r'595 Bowers'),                        'HomeHub'),
    # Brand rebrand: BowersHub -> HomeHub (owner-approved). Compounds before the
    # bare street token.
    (re.compile(r'BowersHub'),                         'HomeHub'),
    (re.compile(r'bowershub'),                          'homehub'),
    (re.compile(r'\bBowers\b'),                        'HomeHub'),
    (re.compile(r'\bbowers\b'),                         'homehub'),
    # Personal email (before the name tokens it contains)
    (re.compile(r'manningmichael2@gmail\.com'),        'admin@example.com'),
    # Home path (before the 'michael' first-name rule)
    (re.compile(r'/home/michael'),                     '/home/user'),
    # Real surnames
    (re.compile(r'Manning'), 'Carter'), (re.compile(r'MANNING'), 'CARTER'), (re.compile(r'manning'), 'carter'),
    (re.compile(r'Nitta'),   'Carter'), (re.compile(r'NITTA'),   'CARTER'), (re.compile(r'nitta'),   'carter'),
    # Household first names (case-preserving)
    (re.compile(r'\bManon\b'),   'Alex'), (re.compile(r'\bMANON\b'),   'ALEX'), (re.compile(r'\bmanon\b'),   'alex'),
    (re.compile(r'\bMichael\b'), 'Sam'),  (re.compile(r'\bMICHAEL\b'), 'SAM'),  (re.compile(r'\bmichael\b'), 'sam'),
    # Internal IP + private repo dir name
    (re.compile(r'100\.106\.180\.101'),                '100.64.0.10'),
    (re.compile(r'KiroProject'),                       'private-ai-hub'),
]

# README-only link fixups: drop references to files that stay private so the
# public README has no dead links. Skipped silently if the text isn't present
# (e.g. after a README restructure) — update these if the README changes.
README_FIXUPS = [
    ("This repo is developed with two agentic tools sharing one repo (Kiro IDE + Claude Code) — see [`CLAUDE.md`](CLAUDE.md) and the running [`context-log.md`](context-log.md) handoff journal.",
     "Migrations are forward-only and auto-applied on startup."),
    ("docs/                    — Cutover notes, screenshots, how-tos\n", "docs/                    — Screenshots\n"),
    (".kiro/                   — Spec-driven workflow (specs + steering)\n", ""),
    ("> The app is `bowershub-ai/` (FastAPI backend + React PWA). A working dev environment is already provisioned; see [`CLAUDE.md`](CLAUDE.md) for the canonical setup.",
     "> The app is `bowershub-ai/` (FastAPI backend + React PWA)."),
]

TEXT_EXT = {'.py', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.json', '.sql', '.md',
            '.sh', '.yml', '.yaml', '.txt', '.ini', '.html', '.css', '.env.example',
            '.toml', '.cfg', '.conf', ''}

def is_text(path):
    _, ext = os.path.splitext(path)
    if path.endswith('.env.example'):
        return True
    if ext.lower() in {'.png', '.jpg', '.jpeg', '.gif', '.ico', '.webp', '.woff',
                        '.woff2', '.ttf', '.otf', '.pdf', '.zip', '.gz'}:
        return False
    return True

changed = 0
for dirpath, _, files in os.walk(root):
    if '/.git' in dirpath:
        continue
    for f in files:
        p = os.path.join(dirpath, f)
        if not is_text(p):
            continue
        try:
            with open(p, encoding='utf-8') as fh:
                text = fh.read()
        except (UnicodeDecodeError, IsADirectoryError):
            continue
        orig = text
        # README fixups match the ORIGINAL prose, so run them before the
        # identifier/brand replacements rewrite the surrounding text.
        if os.path.relpath(p, root) == 'README.md':
            for old, new in README_FIXUPS:
                text = text.replace(old, new)
        for pat, rep in REPLACEMENTS:
            text = pat.sub(rep, text)
        if text != orig:
            with open(p, 'w', encoding='utf-8') as fh:
                fh.write(text)
            changed += 1

print(f"  scrubbed {changed} file(s)")

# ── VERIFY ──────────────────────────────────────────────────────────────────
LEAK = re.compile(
    r'manningmichael2|100\.106\.180\.101|/home/michael|tailc4d58a'
    r'|595\s?bowers|bowershub|\bbowers\b|\bmanning\b|\bnitta\b'
    r'|\bmanon\b|\bmichael\b|KiroProject',
    re.IGNORECASE)
leaks = []
for dirpath, _, files in os.walk(root):
    if '/.git' in dirpath:
        continue
    for f in files:
        p = os.path.join(dirpath, f)
        if not is_text(p):
            continue
        try:
            with open(p, encoding='utf-8') as fh:
                for i, line in enumerate(fh, 1):
                    if LEAK.search(line):
                        leaks.append(f"{os.path.relpath(p, root)}:{i}: {line.strip()[:100]}")
        except (UnicodeDecodeError, IsADirectoryError):
            continue

if leaks:
    print("\n✗ SCRUB VERIFICATION FAILED — personal identifiers survived:")
    for l in leaks[:50]:
        print("   ", l)
    sys.exit(1)
print("  ✓ verification clean — no personal identifiers remain")
PY

# Rebrand the app directory itself (its name carried the street token). Done
# after verification so the scan sees the pre-rename tree.
mv "$STAGE/bowershub-ai" "$STAGE/homehub-ai"

# ── 4. Mirror into the public repo and snapshot-commit ─────────────────────────
mkdir -p "$PUB"
if [ ! -d "$PUB/.git" ]; then
  git -C "$PUB" init -q
  echo "  initialized new public repo at $PUB"
fi
# Mirror staged tree → public working tree, deleting stale files, protecting .git.
rsync -a --delete --filter='P /.git/' "$STAGE/" "$PUB/"

git -C "$PUB" add -A
if git -C "$PUB" diff --cached --quiet; then
  echo "  no changes to commit"
else
  git -C "$PUB" commit -q -m "sync: $LABEL" \
    -m "Scrubbed app-only snapshot from the private source repo." \
    --author="private-ai-hub <noreply@example.com>"
  echo "  ✓ committed snapshot: $(git -C "$PUB" rev-parse --short HEAD)"
fi

echo
echo "Done. Review then publish (NOT done automatically):"
echo "   cd $PUB && git log --stat -1"
echo "   gh repo create private-ai-hub --public --source=. --remote=origin --push"
