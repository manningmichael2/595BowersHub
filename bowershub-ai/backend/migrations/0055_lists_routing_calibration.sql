-- 0055 — Lists v2 Task 11: routing-document enrichment + calibrated thresholds.
--
-- Calibration (real bge-m3 cosine, scripts in the lists-v2 spec) showed the
-- as-built routing document — name · type_label · LIST.description — was too thin
-- to route items: real lists rarely have a per-list description, so the embedded
-- text was often just "Groceries · Grocery · ", giving ~71% accuracy with genuine
-- mis-routes (no threshold separated correct from noise). The fix has two parts:
--   1. the embedding worker now folds the TYPE description into the document
--      (see embedding_worker._LIST_CONTENT_SQL), so every list inherits its type's
--      semantic anchor even with no per-list description; and
--   2. those type descriptions are enriched here with representative example terms.
-- Together this lifts routing to ≥90% with clean correct/noise separation, letting
-- the thresholds calibrate at match=0.40 / margin=0.04 (was the 0.55/0.07 placeholder).
--
-- Forward-only + idempotent. Each UPDATE is guarded on the prior value so it never
-- clobbers an owner's edit (description tweaked in the UI, thresholds tuned in
-- Settings). Changing the type descriptions also bumps every list's content hash,
-- so the embedding worker re-embeds all lists on its next tick (intended).

-- Part 1 — enrich seeded list-type descriptions with example terms (feeds AI routing).
UPDATE public.bh_list_types SET description =
  'Groceries and household shopping by department — food, kitchen and home supplies. '
  'Examples: milk, eggs, bread, bananas, produce, chicken, yogurt, juice, snacks, paper towels, dish soap.'
  WHERE name='grocery' AND is_seed AND description = 'Groceries and household shopping, by department.';

UPDATE public.bh_list_types SET description =
  'Household chores, cleaning and maintenance tasks assigned to people. '
  'Examples: vacuum, mow the lawn, clean the bathroom, do laundry, take out the trash, dishes, dusting.'
  WHERE name='chores' AND is_seed AND description = 'Household chores and tasks, by who is assigned.';

UPDATE public.bh_list_types SET description =
  'Gift ideas and presents for family and friends, with recipient and link. '
  'Examples: birthday present, christmas gift, gift card, toy, book, jewelry, necklace.'
  WHERE name='gifts' AND is_seed AND description = 'Gift ideas, with recipient and link.';

UPDATE public.bh_list_types SET description =
  'General to-dos, errands, reminders and appointments by due date. '
  'Examples: call the dentist, pay bills, renew registration, schedule appointment, email, follow up.'
  WHERE name='todo' AND is_seed AND description = 'General to-dos, by due date.';

UPDATE public.bh_list_types SET description =
  'Packing list of things to bring on a trip or vacation, by section. '
  'Examples: swimsuit, sunscreen, passport, toothbrush, charger, beach towel, travel adapter, clothes.'
  WHERE name='packing' AND is_seed AND description = 'Packing lists, by section.';

-- 'simple' stays intentionally generic — it is the catch-all/default type and must
-- NOT out-score a specific list for an item. Only normalize the trailing copy.
UPDATE public.bh_list_types SET description = 'A simple checklist for anything.'
  WHERE name='simple' AND is_seed AND description = 'A simple checklist.';

-- Part 2 — replace the placeholder routing thresholds with the calibrated values.
-- jsonb equality is key-order independent, so this matches the 0054 seed exactly.
UPDATE public.bh_platform_settings
SET value_json = '{"match_threshold":0.40,"create_threshold":0.35,"ambiguity_margin":0.04}'::jsonb
WHERE key='lists.routing'
  AND value_json = '{"match_threshold":0.55,"create_threshold":0.35,"ambiguity_margin":0.07}'::jsonb;
