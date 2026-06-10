-- Migration 021: Move finance tables to dedicated 'finance' schema
-- 
-- Moves: accounts, transactions, transaction_files, budgets, categories,
--         category_examples, alert_log, email_classified, email_labels
-- From: public → finance
--
-- Creates views in public as backward-compatible aliases (so nothing breaks
-- while we update all the query paths). Views can be dropped in a future
-- migration once all references are confirmed updated.

-- Create the finance schema
CREATE SCHEMA IF NOT EXISTS finance;

-- Move the tables
ALTER TABLE public.accounts SET SCHEMA finance;
ALTER TABLE public.transactions SET SCHEMA finance;
ALTER TABLE public.transaction_files SET SCHEMA finance;
ALTER TABLE public.budgets SET SCHEMA finance;
ALTER TABLE public.categories SET SCHEMA finance;
ALTER TABLE public.category_examples SET SCHEMA finance;
ALTER TABLE public.alert_log SET SCHEMA finance;
ALTER TABLE public.email_classified SET SCHEMA finance;
ALTER TABLE public.email_labels SET SCHEMA finance;

-- Create backward-compatible views in public
-- These let existing queries work without modification during transition.
-- Simple views on single tables are auto-updatable in Postgres (INSERT/UPDATE/DELETE pass through).
CREATE OR REPLACE VIEW public.accounts AS SELECT * FROM finance.accounts;
CREATE OR REPLACE VIEW public.transactions AS SELECT * FROM finance.transactions;
CREATE OR REPLACE VIEW public.transaction_files AS SELECT * FROM finance.transaction_files;
CREATE OR REPLACE VIEW public.budgets AS SELECT * FROM finance.budgets;
CREATE OR REPLACE VIEW public.categories AS SELECT * FROM finance.categories;
CREATE OR REPLACE VIEW public.category_examples AS SELECT * FROM finance.category_examples;
CREATE OR REPLACE VIEW public.alert_log AS SELECT * FROM finance.alert_log;
CREATE OR REPLACE VIEW public.email_classified AS SELECT * FROM finance.email_classified;
CREATE OR REPLACE VIEW public.email_labels AS SELECT * FROM finance.email_labels;

-- Update workspace permitted_schemas to include finance
UPDATE public.bh_workspaces 
SET permitted_schemas = array_append(permitted_schemas, 'finance')
WHERE name = 'Finance' AND NOT ('finance' = ANY(permitted_schemas));

-- Also update General workspace to have finance access (for ask-db)
UPDATE public.bh_workspaces 
SET permitted_schemas = array_append(permitted_schemas, 'finance')
WHERE name = 'General' AND NOT ('finance' = ANY(permitted_schemas));
