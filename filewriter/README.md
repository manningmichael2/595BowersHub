# Filewriter

Small HTTP service for filesystem + IMAP operations that n8n can't easily do itself.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/write` | Write JSON to `/finance/` (legacy) |
| POST | `/probe` | File existence, size, sha256, mime |
| POST | `/read-base64` | Read file as base64 (for vision APIs) |
| POST | `/move` | Move a file with auto-mkdir |
| POST | `/mkdir` | Create directory tree |
| POST | `/write-base64` | Decode and persist a base64 file |
| POST | `/append` | Append text to a file |
| POST | `/read-text` | Read file contents as UTF-8 |
| POST | `/search` | Grep-style search (literal or smart mode) |
| POST | `/list` | List directory contents |
| POST | `/imap/fetch-recent` | Fetch recent emails |
| POST | `/imap/fetch-one` | Fetch single email with attachments |
| POST | `/imap/add-label` | Apply a Gmail label |
| POST | `/imap/mark-read` | Mark email as read |
| POST | `/imap/archive` | Archive email (remove from INBOX) |
| GET | `/health` | Health check |

## Allowed Roots

All filesystem operations are constrained to:
- `/finance` — transaction JSON files
- `/files` — household file repository
- `/knowledge` — personal knowledge base

## Deploy

The service runs as a Docker container on the 595BowersHub server. It's bind-mounted
to the host's filewriter directory, so updating `app.py` on the server and restarting
the container picks up changes immediately.

```bash
# Quick restart (source is bind-mounted):
docker restart filewriter

# Full rebuild (if Dockerfile/requirements change):
cd ~/filewriter
docker build -t filewriter .
docker stop filewriter && docker rm filewriter
docker run -d --name filewriter --restart unless-stopped \
  --network ai-services_ai-network -p 5001:5001 \
  -v /home/michael/finance:/finance \
  -v /home/michael/files:/files \
  -v /home/michael/knowledge:/knowledge \
  --env-file ~/.env.filewriter \
  filewriter
```

## Environment Variables

See `.env.example`. Required for IMAP endpoints only.
