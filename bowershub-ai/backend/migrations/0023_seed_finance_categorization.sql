-- 0023 — Seed data for finance categorization (DML; migrator role has it).
--
-- WHY a category seed: finance.categories is populated only in the live DB —
-- nothing in the 0001..0021 chain creates it — so a from-empty rebuild (the C2
-- promise) and every fresh_db test come up category-empty, leaving the finance
-- system non-functional. This seeds the canonical taxonomy (the exact live
-- tree, 25 rows) so live and fresh converge; ON CONFLICT (name) DO NOTHING is a
-- genuine no-op against prod. Taxonomy stays as-is (90% of live transactions
-- reference these ids — a wholesale change would orphan them; §10-T1 defers any
-- Plaid-PFC alignment to a separate reversible additive migration).
--
-- Refs: .kiro/specs/finance-categorization (Task 2; B1, B2, R1.3, R2.5).

-- 1a. Top-level categories (parent_id NULL) — must precede children (self-FK).
INSERT INTO finance.categories (id, name, is_system, parent_id) VALUES
    (4,  'Transportation', true, NULL),
    (6,  'Subscriptions',  true, NULL),
    (9,  'Insurance',      true, NULL),
    (10, 'Medical',        true, NULL),
    (11, 'Shopping',       true, NULL),
    (12, 'Entertainment',  true, NULL),
    (13, 'Transfer',       true, NULL),
    (14, 'Income',         true, NULL),
    (15, 'ATM',            true, NULL),
    (17, 'Other',          true, NULL),
    (19, 'House',          true, NULL),
    (20, 'Food',           true, NULL),
    (22, 'Travel',         true, NULL),
    (23, 'Woodshop',       true, NULL)
ON CONFLICT (name) DO NOTHING;

-- 1b. Sub-categories.
INSERT INTO finance.categories (id, name, is_system, parent_id) VALUES
    (31, 'Trans_Gas',             true, 4),
    (32, 'Trans_Car_Maintenance', true, 4),
    (33, 'Trans_Car_Insurance',   true, 4),
    (34, 'Trans_Public_Transit',  true, 4),
    (24, 'House_Mortgage',        true, 19),
    (25, 'House_Utilities',       true, 19),
    (26, 'House_Maintenance',     true, 19),
    (27, 'House_Improvement',     true, 19),
    (28, 'House_Furniture',       true, 19),
    (29, 'Food_Groceries',        true, 20),
    (30, 'Food_Dining',           true, 20)
ON CONFLICT (name) DO NOTHING;

-- Keep the id sequence ahead of the explicit ids we inserted (no-op on prod,
-- where the sequence is already past max(id)).
SELECT setval('finance.categories_id_seq', (SELECT max(id) FROM finance.categories));

-- 2. Categorizer config defaults (R2.5 per-tier thresholds, rollout gate, kNN
--    sizing, recurring tolerances). Feature-gate starts at 'legacy' so the new
--    cascade is dark until explicitly enabled (shadow → cascade).
INSERT INTO finance.categorizer_config (key, value) VALUES
    ('categorizer_engine', '"legacy"'::jsonb),
    ('thresholds',    '{"rule":1.0,"merchant_memory":0.8,"embedding_knn":0.7,"llm":0.6,"transfer":0.9}'::jsonb),
    ('tiers_enabled', '{"transfer":true,"rule":true,"merchant_memory":true,"embedding_knn":true,"llm":true}'::jsonb),
    ('knn',           '{"k":15,"min_neighbors":3}'::jsonb),
    ('recurring',     '{"min_occurrences":3,"amount_tolerance_pct":15,"interval_tolerance_days":4}'::jsonb)
ON CONFLICT (key) DO NOTHING;

-- 3. Privacy-safe `categorizer` role default (B1). resolve_role() cold-starts to
--    the hosted `chat` model unless this alias exists, which would send txn data
--    off-box. Inherit whatever `local` points to (guarantees a valid
--    bh_model_rates FK and keeps the default on-box). Task 13 repoints this to
--    the local model chosen empirically against the eval set.
INSERT INTO public.bh_model_aliases (role, model_id)
SELECT 'categorizer', model_id FROM public.bh_model_aliases WHERE role = 'local'
ON CONFLICT (role) DO NOTHING;

-- 4. Starter MCC → category map (R1.3). A representative set mapped to the live
--    taxonomy; the full ISO-18245 dataset is a follow-up data load. category_id
--    resolved by name (categories seeded above).
INSERT INTO finance.mcc_categories (mcc, category_id, description)
SELECT m.mcc, c.id, m.descr
FROM (VALUES
    ('5411', 'Food_Groceries',       'Grocery stores, supermarkets'),
    ('5422', 'Food_Groceries',       'Freezer/meat provisioners'),
    ('5812', 'Food_Dining',          'Eating places, restaurants'),
    ('5814', 'Food_Dining',          'Fast food restaurants'),
    ('5499', 'Food_Groceries',       'Misc food stores / convenience'),
    ('5541', 'Trans_Gas',            'Service stations'),
    ('5542', 'Trans_Gas',            'Automated fuel dispensers'),
    ('4111', 'Trans_Public_Transit', 'Local/suburban commuter transport'),
    ('4121', 'Trans_Public_Transit', 'Taxicabs and rideshares'),
    ('7538', 'Trans_Car_Maintenance','Auto service shops'),
    ('5912', 'Medical',              'Drug stores and pharmacies'),
    ('8011', 'Medical',              'Doctors and physicians'),
    ('8062', 'Medical',              'Hospitals'),
    ('4899', 'Subscriptions',        'Cable, satellite, streaming'),
    ('5734', 'Subscriptions',        'Computer software stores'),
    ('5311', 'Shopping',             'Department stores'),
    ('5999', 'Shopping',             'Misc/specialty retail'),
    ('5942', 'Shopping',             'Book stores'),
    ('7832', 'Entertainment',        'Movie theaters'),
    ('7996', 'Entertainment',        'Amusement parks'),
    ('7011', 'Travel',               'Hotels, motels, resorts'),
    ('4511', 'Travel',               'Airlines'),
    ('6300', 'Insurance',            'Insurance sales/underwriting'),
    ('4900', 'House_Utilities',      'Utilities — electric, gas, water'),
    ('6011', 'ATM',                  'Automated cash disbursements')
) AS m(mcc, cat_name, descr)
JOIN finance.categories c ON c.name = m.cat_name
ON CONFLICT (mcc) DO NOTHING;
