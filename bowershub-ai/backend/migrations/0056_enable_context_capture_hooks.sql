-- 0056 — Turn ON proactive context capture.
--
-- The Context Harvester (services/context_capture.py) and its hook action
-- ('capture_context' in hook_engine) were built but never connected: nothing
-- dispatched the 'message_received' event, and no capture_context hook existed,
-- so it had never run in production. The dispatch is now wired in
-- websocket/handlers.py; this migration creates the hook that the dispatch fires.
--
-- One enabled capture_context hook per existing workspace (hooks are
-- workspace-scoped). Idempotent: skips any workspace that already has one, so a
-- re-run — or a workspace where the owner later disables/edits the hook — is
-- never clobbered. New workspaces created after this migration won't auto-get a
-- hook (a follow-up could seed on workspace creation); existing ones are covered.
--
-- Extraction runs on the LOCAL Ollama model (resolve_role('local')) so every
-- exchange — including Finance — is scanned privately on-box, and the per-user
-- `settings_json.context_capture_disabled` opt-out still short-circuits it.

INSERT INTO public.bh_hooks
    (workspace_id, name, description, event_type, action_type, action_config, is_enabled, created_by)
SELECT w.id,
       'Auto context capture',
       'Silently extract durable facts from each exchange into semantic memory (pgvector).',
       'message_received', 'capture_context', '{}'::jsonb, true, NULL
FROM public.bh_workspaces w
WHERE NOT EXISTS (
    SELECT 1 FROM public.bh_hooks h
    WHERE h.workspace_id = w.id AND h.action_type = 'capture_context'
);

-- The fact-extraction model (DB-configurable, NO-HARDCODING). Default qwen3:8b:
-- calibration showed llama3.2:3b (the generic 'local' alias) caught only ~1/3 of
-- facts, while qwen3:8b caught all with correct topics. Latency (~25s) is fine —
-- capture runs as a fire-and-forget background task after the reply. Editable
-- without a deploy; runs on local Ollama so conversations never leave the box.
INSERT INTO public.bh_platform_settings (key, value_json)
SELECT 'context_capture.model', '{"model":"qwen3:8b"}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM public.bh_platform_settings WHERE key = 'context_capture.model'
);
