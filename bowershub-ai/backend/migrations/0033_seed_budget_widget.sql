-- 0033 — Register the Budget Progress dashboard widget (DB-driven widget registry).
--
-- NO-HARDCODING: dashboard widgets are rows in public.bh_dashboard_widgets read by
-- the dashboard API; adding one is a data change. Guarded so re-applying is a no-op.
-- Frontend maps widget_key 'budget_progress' → BudgetProgressWidget in
-- components/dashboard/WidgetRegistry.ts.
--
-- Refs: .kiro/specs/finance-budgets-splits (R3.4 dashboard surfacing).

INSERT INTO public.bh_dashboard_widgets
    (widget_key, display_name, description, category, data_endpoint, default_config, sort_order, is_active)
SELECT 'budget_progress', 'Budget Progress',
       'This month''s spending vs budget by category.', 'finance',
       '/api/dashboard/finance/budgets', '{}'::jsonb, 50, true
WHERE NOT EXISTS (
    SELECT 1 FROM public.bh_dashboard_widgets WHERE widget_key = 'budget_progress'
);
