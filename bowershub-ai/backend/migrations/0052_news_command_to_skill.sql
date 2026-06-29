-- 0052 — convert /news from a special-routed command to a skill-backed one.
--
-- Proof-of-pattern for collapsing capability commands onto their skills (the
-- NO-HARDCODING direction). /news is the clean case: its special-route handler
-- just did `category = args or "top"` → get_news(category), and the news service
-- already resolves an empty/None category to "top" — so a `{"category": "$args"}`
-- template reproduces it exactly (`/news` → top, `/news sports` → sports). The
-- code's `elif command == "/news"` branch + `_handle_news_command` are removed in
-- the same change.
--
-- NOT every command converts this cleanly: /recall (--list/--recent subcommands),
-- /weather (filters flag-words out of the location), /sports (--schedule parsing)
-- etc. carry real arg logic a flat $args template can't replicate — those stay
-- special-routed unless their skill is first made robust to raw command args.

UPDATE public.bh_slash_commands
   SET skill_id = (SELECT id FROM public.bh_skills WHERE name = 'news'),
       param_template = '{"category": "$args"}'::jsonb
 WHERE command = '/news' AND workspace_id IS NULL;
