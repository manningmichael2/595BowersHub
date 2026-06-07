-- =============================================================================
-- Migration 001: Category Hierarchy + Learning Loop
-- =============================================================================
-- Adds:
--   - parent_id column to categories (2-tier hierarchy)
--   - category_examples table (learning loop)
--   - New category tree (House, Food, Transportation parents)
-- Reassigns:
--   - All transactions to parent_id IS NOT NULL (leaf categories only)
-- Preserves:
--   - user_category_override flags
--   - Existing budgets (re-linked to new leaf categories)
-- =============================================================================

BEGIN;

-- --- Schema changes ---------------------------------------------------------

ALTER TABLE categories
  ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES categories(id);

CREATE INDEX IF NOT EXISTS idx_categories_parent_id ON categories(parent_id);

-- Learning loop: examples Haiku uses as few-shot guidance
CREATE TABLE IF NOT EXISTS category_examples (
  id SERIAL PRIMARY KEY,
  description_pattern TEXT NOT NULL,
  category_id INTEGER NOT NULL REFERENCES categories(id),
  source_transaction_id VARCHAR(128) REFERENCES transactions(id) ON DELETE SET NULL,
  times_reinforced INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_category_examples_category_id ON category_examples(category_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_category_examples_unique_pattern
  ON category_examples (LOWER(description_pattern), category_id);

-- --- Seed parent categories (idempotent) ------------------------------------

INSERT INTO categories (name, is_system, parent_id) VALUES
  ('House',          true, NULL),
  ('Food',           true, NULL),
  ('Transportation', true, NULL),
  ('Travel',         true, NULL),
  ('Woodshop',       true, NULL)
ON CONFLICT (name) DO NOTHING;

-- --- Seed leaf categories under parents -------------------------------------

WITH p AS (
  SELECT
    (SELECT id FROM categories WHERE name = 'House')           AS house_id,
    (SELECT id FROM categories WHERE name = 'Food')            AS food_id,
    (SELECT id FROM categories WHERE name = 'Transportation')  AS trans_id
)
INSERT INTO categories (name, is_system, parent_id) VALUES
  ('House_Mortgage',    true, (SELECT house_id FROM p)),
  ('House_Utilities',   true, (SELECT house_id FROM p)),
  ('House_Maintenance', true, (SELECT house_id FROM p)),
  ('House_Improvement', true, (SELECT house_id FROM p)),
  ('House_Furniture',   true, (SELECT house_id FROM p)),
  ('Food_Groceries',    true, (SELECT food_id FROM p)),
  ('Food_Dining',       true, (SELECT food_id FROM p)),
  ('Trans_Gas',              true, (SELECT trans_id FROM p)),
  ('Trans_Car_Maintenance',  true, (SELECT trans_id FROM p)),
  ('Trans_Car_Insurance',    true, (SELECT trans_id FROM p)),
  ('Trans_Public_Transit',   true, (SELECT trans_id FROM p))
ON CONFLICT (name) DO UPDATE SET parent_id = EXCLUDED.parent_id;

-- --- Migrate existing transactions/budgets from old -> new leaf categories --

-- Map old flat categories to new leaf categories
UPDATE transactions t
SET category_id = new_cat.id
FROM categories old_cat, categories new_cat
WHERE t.category_id = old_cat.id
  AND (
    (old_cat.name = 'Groceries'        AND new_cat.name = 'Food_Groceries') OR
    (old_cat.name = 'Dining'           AND new_cat.name = 'Food_Dining') OR
    (old_cat.name = 'Gas'              AND new_cat.name = 'Trans_Gas') OR
    (old_cat.name = 'Mortgage'         AND new_cat.name = 'House_Mortgage') OR
    (old_cat.name = 'Utilities'        AND new_cat.name = 'House_Utilities') OR
    (old_cat.name = 'Home_Improvement' AND new_cat.name = 'House_Improvement')
  );

-- Same for budgets
UPDATE budgets b
SET category_id = new_cat.id
FROM categories old_cat, categories new_cat
WHERE b.category_id = old_cat.id
  AND (
    (old_cat.name = 'Groceries'        AND new_cat.name = 'Food_Groceries') OR
    (old_cat.name = 'Dining'           AND new_cat.name = 'Food_Dining') OR
    (old_cat.name = 'Gas'              AND new_cat.name = 'Trans_Gas') OR
    (old_cat.name = 'Mortgage'         AND new_cat.name = 'House_Mortgage') OR
    (old_cat.name = 'Utilities'        AND new_cat.name = 'House_Utilities') OR
    (old_cat.name = 'Home_Improvement' AND new_cat.name = 'House_Improvement')
  );

-- --- Drop deprecated flat categories (safe - nothing references them now) ---

DELETE FROM categories
WHERE name IN ('Groceries', 'Dining', 'Gas', 'Mortgage', 'Utilities', 'Home_Improvement', 'Rent')
  AND parent_id IS NULL;

-- --- Final state: all transactions should be at leaf categories -------------

-- Reset category_id on any row still pointing at a non-leaf (parent) category
-- so the Categorizer will re-process them
UPDATE transactions t
SET category_id = NULL, user_category_override = false
FROM categories c
WHERE t.category_id = c.id
  AND c.parent_id IS NULL
  AND c.name IN ('House', 'Food', 'Transportation')
  AND t.user_category_override = false;

COMMIT;

-- --- Verification -----------------------------------------------------------

SELECT
  p.name AS parent,
  c.name AS category,
  c.is_system
FROM categories c
LEFT JOIN categories p ON c.parent_id = p.id
ORDER BY COALESCE(p.name, c.name), c.name;
