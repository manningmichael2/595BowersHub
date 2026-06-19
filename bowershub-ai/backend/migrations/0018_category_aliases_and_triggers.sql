-- Migration 0018: Category Aliases and Manual Learning Triggers
-- This migration implements DB-driven category intelligence and automated learning from manual updates.

-- 1. Create category_aliases table
CREATE TABLE IF NOT EXISTS finance.category_aliases (
    id SERIAL PRIMARY KEY,
    alias TEXT UNIQUE NOT NULL, -- Lowercase natural language term (e.g. 'bar', 'grocery')
    category_id INTEGER NOT NULL REFERENCES finance.categories(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed initial aliases based on previous hardcoding
INSERT INTO finance.category_aliases (alias, category_id)
SELECT 'bar', id FROM finance.categories WHERE name = 'Food_Dining' ON CONFLICT DO NOTHING;
INSERT INTO finance.category_aliases (alias, category_id)
SELECT 'restaurant', id FROM finance.categories WHERE name = 'Food_Dining' ON CONFLICT DO NOTHING;
INSERT INTO finance.category_aliases (alias, category_id)
SELECT 'dining', id FROM finance.categories WHERE name = 'Food_Dining' ON CONFLICT DO NOTHING;
INSERT INTO finance.category_aliases (alias, category_id)
SELECT 'grocery', id FROM finance.categories WHERE name = 'Food_Groceries' ON CONFLICT DO NOTHING;
INSERT INTO finance.category_aliases (alias, category_id)
SELECT 'groceries', id FROM finance.categories WHERE name = 'Food_Groceries' ON CONFLICT DO NOTHING;
INSERT INTO finance.category_aliases (alias, category_id)
SELECT 'gas', id FROM finance.categories WHERE name = 'Trans_Gas' ON CONFLICT DO NOTHING;
INSERT INTO finance.category_aliases (alias, category_id)
SELECT 'fuel', id FROM finance.categories WHERE name = 'Trans_Gas' ON CONFLICT DO NOTHING;
INSERT INTO finance.category_aliases (alias, category_id)
SELECT 'car insurance', id FROM finance.categories WHERE name = 'Trans_Car_Insurance' ON CONFLICT DO NOTHING;
INSERT INTO finance.category_aliases (alias, category_id)
SELECT 'utilities', id FROM finance.categories WHERE name = 'House_Utilities' ON CONFLICT DO NOTHING;
INSERT INTO finance.category_aliases (alias, category_id)
SELECT 'electric', id FROM finance.categories WHERE name = 'House_Utilities' ON CONFLICT DO NOTHING;
INSERT INTO finance.category_aliases (alias, category_id)
SELECT 'water', id FROM finance.categories WHERE name = 'House_Utilities' ON CONFLICT DO NOTHING;
INSERT INTO finance.category_aliases (alias, category_id)
SELECT 'internet', id FROM finance.categories WHERE name = 'Subscriptions' ON CONFLICT DO NOTHING;

-- 2. Create learning trigger function
CREATE OR REPLACE FUNCTION finance.fn_learn_from_manual_override()
RETURNS TRIGGER AS $$
DECLARE
    v_pattern TEXT;
BEGIN
    -- Only trigger if category_id changed and user_category_override is true
    IF (TG_OP = 'UPDATE' AND NEW.category_id IS NOT NULL AND NEW.user_category_override = true AND (OLD.category_id IS NULL OR OLD.category_id != NEW.category_id)) THEN
        
        -- Extract pattern: first alphabetic word >= 3 chars
        v_pattern := (SELECT (regexp_matches(NEW.description, '[A-Za-z]{3,}', 'g'))[1] LIMIT 1);
        
        IF v_pattern IS NOT NULL THEN
            v_pattern := UPPER(v_pattern);
            
            -- Upsert into category_examples
            INSERT INTO finance.category_examples (description_pattern, category_id, times_reinforced, updated_at)
            VALUES (v_pattern, NEW.category_id, 1, NOW())
            ON CONFLICT (lower(description_pattern), category_id) DO UPDATE
            SET times_reinforced = finance.category_examples.times_reinforced + 1,
                updated_at = NOW();
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 3. Attach trigger to transactions table
DROP TRIGGER IF EXISTS trg_learn_from_manual_override ON finance.transactions;
CREATE TRIGGER trg_learn_from_manual_override
AFTER UPDATE ON finance.transactions
FOR EACH ROW
EXECUTE FUNCTION finance.fn_learn_from_manual_override();
