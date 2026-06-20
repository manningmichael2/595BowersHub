-- 0025 — Seed finance.eval_labels (R2.7).
--
-- Hand-verified raw-descriptor → expected-category pairs, INCLUDING transfer and
-- debt-payment cases (the asymmetric-gate failure modes the eval must catch).
-- This is the labeled set the eval harness (services/categorization_eval.py)
-- scores each tier / candidate model against, so R2.4's model choice and R2.5's
-- thresholds are empirical (Task 13) rather than asserted.
--
-- DML; migrator role has it. category_id resolved by name (categories seeded in
-- 0023, present on both fresh_db and prod). Idempotent: guarded by a NOT EXISTS
-- on (description, COALESCE(amount)) so re-applying is a true no-op.
--
-- Refs: .kiro/specs/finance-categorization (Task 4; R2.7).

INSERT INTO finance.eval_labels (description, account_type, amount, expected_category_id, is_transfer_expected, notes)
SELECT v.description, v.account_type, v.amount,
       (SELECT id FROM finance.categories c WHERE c.name = v.cat_name),
       v.is_transfer, v.notes
FROM (VALUES
    -- (description, account_type, amount, expected category name, is_transfer, notes)
    ('COSTCO WHSE #0393 MADISON HEIGHMI', 'credit_card', -184.21, 'Food_Groceries',   false, 'warehouse club groceries'),
    ('KROGER #456 ANN ARBOR MI',          'credit_card', -73.55,  'Food_Groceries',   false, 'grocery'),
    ('MEIJER #123',                       'credit_card', -52.10,  'Food_Groceries',   false, 'supermarket'),
    ('TST* THE COFFEE HOUSE',             'credit_card', -6.75,   'Food_Dining',      false, 'toast POS restaurant'),
    ('SQ *SUNRISE BAKERY',               'credit_card', -14.20,  'Food_Dining',      false, 'square POS dining'),
    ('UBER EATS',                         'credit_card', -31.40,  'Food_Dining',      false, 'food delivery'),
    ('SHELL OIL 574212',                  'credit_card', -48.00,  'Trans_Gas',        false, 'fuel'),
    ('MARATHON PETRO 12',                 'credit_card', -41.13,  'Trans_Gas',        false, 'fuel'),
    ('DTE ENERGY',                        'checking',    -142.88, 'House_Utilities',  false, 'electric/gas utility'),
    ('CITY OF ANN ARBOR WATER',           'checking',    -88.40,  'House_Utilities',  false, 'water utility'),
    ('NETFLIX.COM',                       'credit_card', -15.49,  'Subscriptions',    false, 'streaming'),
    ('SPOTIFY USA',                       'credit_card', -10.99,  'Subscriptions',    false, 'streaming'),
    ('ROCKLER WOODWORKING',               'credit_card', -212.00, 'Woodshop',         false, 'woodworking supplies'),
    ('HARBOR FREIGHT TOOLS',              'credit_card', -64.30,  'Woodshop',         false, 'tools'),
    ('DELTA AIR LINES',                   'credit_card', -412.20, 'Travel',           false, 'airline'),
    ('MARRIOTT HOTELS',                   'credit_card', -289.00, 'Travel',           false, 'hotel'),
    ('CVS PHARMACY #871',                 'credit_card', -23.18,  'Medical',          false, 'pharmacy'),
    ('AMAZON.COM*RT4G',                   'credit_card', -39.99,  'Shopping',         false, 'general retail'),
    ('PAYROLL DEPOSIT EMPLOYER INC',      'checking',    3120.55, 'Income',           false, 'paycheck'),
    -- Transfer / debt-payment cases (the asymmetric-gate must catch these):
    ('TRANSFER TO SAVINGS XXXX1234',      'checking',    -500.00, 'Transfer',         true,  'inter-account transfer out'),
    ('TRANSFER FROM CHECKING XXXX5678',   'savings',     500.00,  'Transfer',         true,  'inter-account transfer in'),
    ('ONLINE PAYMENT THANK YOU',          'credit_card', 250.00,  'Transfer',         true,  'credit-card payment (liability paydown)'),
    ('CHASE CREDIT CRD AUTOPAY',          'checking',    -250.00, 'Transfer',         true,  'autopay into liability'),
    ('LOAN PMT PRINCIPAL',                'loan',        -610.00, 'Transfer',         true,  'loan payment into liability'),
    ('ATM WITHDRAWAL #0921',              'checking',    -100.00, 'ATM',              false, 'cash withdrawal — NOT a transfer')
) AS v(description, account_type, amount, cat_name, is_transfer, notes)
WHERE NOT EXISTS (
    SELECT 1 FROM finance.eval_labels e
    WHERE e.description = v.description
      AND e.amount IS NOT DISTINCT FROM v.amount
);
