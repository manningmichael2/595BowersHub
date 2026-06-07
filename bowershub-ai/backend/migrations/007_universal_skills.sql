-- Make ask-db (universal NL->SQL) and recall available in ALL workspaces.
-- These skills query any schema the user has data in, so they should be globally available.
-- The actual data isolation happens at the schema level via permitted_schemas.

INSERT INTO public.bh_workspace_skills (workspace_id, skill_id)
SELECT w.id, s.id
FROM public.bh_workspaces w, public.bh_skills s
WHERE s.name IN ('ask-db', 'recall', 'remember', 'list-files', 'weather')
ON CONFLICT DO NOTHING;
