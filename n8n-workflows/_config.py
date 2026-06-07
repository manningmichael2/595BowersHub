"""Shared configuration for n8n workflow build scripts.

The n8n API key is read from the N8N_API_KEY environment variable.
Set it before running any build script:

    export N8N_API_KEY="your-key-here"

Or create a .env file and source it:

    source .env && python build-finance-query.py
"""
import os
import sys

N8N_URL = os.environ.get("N8N_URL", "http://100.106.180.101:5678")
API_KEY = os.environ.get("N8N_API_KEY", "")

if not API_KEY:
    print("ERROR: N8N_API_KEY environment variable is not set.", file=sys.stderr)
    print("Set it with: export N8N_API_KEY='your-key-here'", file=sys.stderr)
    print("The key is stored in Dashlane under '595BowersHub n8n API Key'.", file=sys.stderr)
    sys.exit(1)
