-- 0048 — register the existing list/shopping-list skill so the assistant can use it.
--
-- The implementation already exists end-to-end — `bh_lists` + `bh_list_items`
-- (baseline 0001), `services/lists.py` (full CRUD), and the
-- `@native_skill("list","lists","shopping-list")` handler in
-- `services/skills/lists.py` — but it was never registered in `bh_skills`, so the
-- router/LLM could never dispatch to it (and there was no slash command). This
-- registers it (native:// handler) and adds a `/list` command linked to it.
--
-- Once registered, the LLM router can pick it for natural language ("add milk to
-- the list", "what's on the shopping list", "we're out of eggs") even without the
-- slash command.
--
-- Note (owner decision, not changed here): `bh_lists.user_id` makes lists
-- per-user. For a household, a shared grocery list is more natural — a follow-up
-- can make the default `shopping` list household-shared (the `added_by` column on
-- items already anticipates multiple contributors).

INSERT INTO public.bh_skills
    (name, description, webhook_url, http_method, param_schema, response_hint,
     is_active, restricted_users, created_at, is_read_only)
VALUES (
    'list',
    'Manage lists — shopping, to-do, packing, etc. Add items, check them off '
    '(bought/done), remove, clear completed, or view. Use for requests like '
    '"add milk to the shopping list", "what''s on the list", "we''re out of eggs", '
    '"check off bread", or "clear the list".',
    'native://list',
    'POST',
    '{
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "view | add | check | remove | clear | all (default: view)"},
            "list_name": {"type": "string", "description": "Which list (default: shopping)"},
            "items": {"type": "array", "items": {"type": "string"}, "description": "Item names for add/check/remove"}
        }
    }'::jsonb,
    'text',
    true,
    '{}',
    now(),
    false
);

-- Slash command linked to the skill (one of the few commands that dispatches
-- through the skill system rather than special-case routing).
INSERT INTO public.bh_slash_commands
    (command, description, skill_id, param_template, workspace_id, is_active, flags)
VALUES (
    '/list',
    'Manage your lists (shopping, to-do, packing, …)',
    (SELECT id FROM public.bh_skills WHERE name = 'list'),
    '{}',
    NULL,
    true,
    '[{"flag": "--all", "description": "Show all your lists"},
      {"flag": "--clear", "description": "Remove checked-off items"}]'::jsonb
);
