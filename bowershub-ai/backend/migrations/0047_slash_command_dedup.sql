-- 0047 — slash-command cleanup: de-duplicate global commands + prevent recurrence.
--
-- A freshly-migrated audit found `/schedule` seeded twice (ids 24 & 26 — identical
-- command/description/flags). bh_slash_commands has no uniqueness guard on the
-- command name, so the duplicate rode along silently and the picker would list
-- `/schedule` twice. This de-dupes any global (workspace_id IS NULL) command that
-- appears more than once, keeping the lowest id, and adds a partial unique index so
-- a global command can't be duplicated again.
--
-- Scope note: only GLOBAL commands are de-duped/constrained. Workspace-scoped
-- commands (workspace_id set) may legitimately reuse a name across workspaces, so
-- they're left untouched. Reversible: commands are DB rows, re-addable via Admin.

-- De-dup global commands, keeping the lowest id per name.
DELETE FROM public.bh_slash_commands a
 USING public.bh_slash_commands b
 WHERE a.workspace_id IS NULL
   AND b.workspace_id IS NULL
   AND a.command = b.command
   AND a.id > b.id;

-- Guard against re-duplication of global commands.
CREATE UNIQUE INDEX IF NOT EXISTS bh_slash_commands_global_command_key
    ON public.bh_slash_commands (command)
 WHERE workspace_id IS NULL;
