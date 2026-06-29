-- 0050 — register a read-email skill so the assistant can check the inbox.
--
-- Email was send-only at the skill layer (`send-email`); a Gmail IMAP read path
-- existed only inside the dashboard widget. This registers the new
-- @native_skill("read-email","check-email","inbox") handler (services/email_reader.py)
-- so the LLM router can summarize the inbox for requests like "what's in my email",
-- "any unread mail", or "did I hear from the bank". Read-only.

INSERT INTO public.bh_skills
    (name, description, webhook_url, http_method, param_schema, response_hint,
     is_active, restricted_users, created_at, is_read_only)
VALUES (
    'read-email',
    'Read/summarize the recent email inbox — senders, subjects, and how many are '
    'unread. Use for "check my email", "any unread mail", "what''s in my inbox", '
    '"did I hear from <someone>". Read-only (does not send).',
    'native://read-email',
    'GET',
    '{
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "How many recent messages (default 10, max 25)"},
            "unread_only": {"type": "boolean", "description": "Only unread messages"}
        }
    }'::jsonb,
    'text',
    true,
    '{}',
    now(),
    true
);
