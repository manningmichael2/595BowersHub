-- 0054 — Lists v2: generic typed-list handler.
--
-- Turns the simple Lists feature into a lightweight typed-property engine.
-- A list has a TYPE (grocery/chores/gifts/todo/packing/simple); every field a
-- list can hold is a row in bh_list_field_defs across three scopes (core/type/
-- list) that merge by `key` with precedence list > type > core into one
-- effective schema. Hot cross-cutting fields are real typed columns on
-- bh_list_items; the user-extensible tail lives in a JSONB `attributes` column.
-- Stores/aisles/category-aliases are first-class DB-driven config (NO-HARDCODING).
--
-- This migration is additive + forward-only + applies on a fresh empty DB. The
-- runner executes it in a single transaction, so the one risky step (the R2.2
-- dedupe-then-constrain in Part 7) is atomic with everything else.
-- See .kiro/specs/lists-v2/design.md for the full rationale.

-- ─────────────────────────────────────────────────────────────────────────────
-- Part 1 — List types
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.bh_list_types (
    id            serial PRIMARY KEY,
    name          text NOT NULL,                   -- machine key, e.g. 'grocery'
    label         text NOT NULL,
    icon          text,
    description   text,                             -- feeds AI routing + UI
    group_by      text,                             -- field key to group by (NULL = none)
    default_sort  text NOT NULL DEFAULT 'recent',   -- must be a sort-whitelist key
    default_order text NOT NULL DEFAULT 'desc' CHECK (default_order IN ('asc','desc')),
    category_set  jsonb NOT NULL DEFAULT '[]'::jsonb,  -- ordered [{key,label,sort_order}]
    is_active     boolean NOT NULL DEFAULT true,
    is_seed       boolean NOT NULL DEFAULT false,
    sort_order    integer NOT NULL DEFAULT 0,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_list_types_name ON public.bh_list_types (LOWER(name));

-- ─────────────────────────────────────────────────────────────────────────────
-- Part 2 — Field definitions (the spine)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.bh_list_field_defs (
    id             serial PRIMARY KEY,
    scope          text NOT NULL CHECK (scope IN ('core','type','list')),
    list_type_id   integer REFERENCES public.bh_list_types(id) ON DELETE CASCADE,
    list_id        integer REFERENCES public.bh_lists(id)      ON DELETE CASCADE,
    key            text NOT NULL,                   -- stable id; column name when storage='column'
    label          text NOT NULL,
    col_type       text NOT NULL CHECK (col_type IN
                     ('text','number','date','checkbox','single_select','multi_select','url')),
    storage        text NOT NULL DEFAULT 'attribute' CHECK (storage IN ('column','attribute')),
    options        jsonb,                           -- inline [{value,label,sort_order}] for selects
    options_source text,                            -- 'stores' | 'users' | NULL (inline)
    required       boolean NOT NULL DEFAULT false,
    is_active      boolean NOT NULL DEFAULT true,   -- soft remove keeps stored values
    groupable      boolean NOT NULL DEFAULT false,
    sortable       boolean NOT NULL DEFAULT false,
    filterable     boolean NOT NULL DEFAULT false,
    validation     jsonb,                           -- optional {min,max,regex}
    sort_order     integer NOT NULL DEFAULT 0,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT field_scope_target CHECK (
        (scope='core' AND list_type_id IS NULL AND list_id IS NULL) OR
        (scope='type' AND list_type_id IS NOT NULL AND list_id IS NULL) OR
        (scope='list' AND list_id IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_fielddef_core ON public.bh_list_field_defs (key)              WHERE scope='core';
CREATE UNIQUE INDEX IF NOT EXISTS uq_fielddef_type ON public.bh_list_field_defs (list_type_id,key) WHERE scope='type';
CREATE UNIQUE INDEX IF NOT EXISTS uq_fielddef_list ON public.bh_list_field_defs (list_id,key)      WHERE scope='list';

-- ─────────────────────────────────────────────────────────────────────────────
-- Part 3 — Column additions on bh_lists / bh_list_items
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE public.bh_lists
    ADD COLUMN IF NOT EXISTS list_type_id integer REFERENCES public.bh_list_types(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS notes        text;     -- merge-audit note target (Part 7)

ALTER TABLE public.bh_list_items
    ADD COLUMN IF NOT EXISTS category         text,
    ADD COLUMN IF NOT EXISTS due_date         timestamptz,
    ADD COLUMN IF NOT EXISTS assignee_user_id integer,                  -- FK added below
    ADD COLUMN IF NOT EXISTS sort_order       double precision,         -- fractional ranking
    ADD COLUMN IF NOT EXISTS attributes       jsonb NOT NULL DEFAULT '{}'::jsonb;

-- assignee FK is ON DELETE SET NULL — deliberately UNLIKE bh_lists.user_id CASCADE,
-- so deleting a household member nulls assignments but never deletes the items.
DO $$ BEGIN
    ALTER TABLE public.bh_list_items
        ADD CONSTRAINT bh_list_items_assignee_fkey
        FOREIGN KEY (assignee_user_id) REFERENCES public.bh_users(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE INDEX IF NOT EXISTS idx_list_items_sort     ON public.bh_list_items (list_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_list_items_category ON public.bh_list_items (list_id, category);
CREATE INDEX IF NOT EXISTS idx_list_items_assignee ON public.bh_list_items (assignee_user_id);
CREATE INDEX IF NOT EXISTS idx_list_items_attrs    ON public.bh_list_items USING gin (attributes);
CREATE INDEX IF NOT EXISTS idx_lists_type          ON public.bh_lists (list_type_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Part 4 — Stores, aisle layouts, grocery category aliases (first-class config)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.bh_stores (
    id         serial PRIMARY KEY,
    name       text NOT NULL,
    is_active  boolean NOT NULL DEFAULT true,
    sort_order integer NOT NULL DEFAULT 0,
    created_by integer REFERENCES public.bh_users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_stores_name ON public.bh_stores (LOWER(name));

CREATE TABLE IF NOT EXISTS public.bh_store_aisles (   -- store → ordered departments (walk order)
    id         serial PRIMARY KEY,
    store_id   integer NOT NULL REFERENCES public.bh_stores(id) ON DELETE CASCADE,
    department text NOT NULL,                          -- matches a category_set key
    sort_order integer NOT NULL,
    UNIQUE (store_id, department)
);

CREATE TABLE IF NOT EXISTS public.bh_item_category_aliases (   -- grocery auto-categorize
    id           serial PRIMARY KEY,
    list_type_id integer REFERENCES public.bh_list_types(id) ON DELETE CASCADE,  -- NULL = any
    alias        text NOT NULL,
    department   text NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_item_alias
    ON public.bh_item_category_aliases (LOWER(alias), COALESCE(list_type_id, 0));

-- ─────────────────────────────────────────────────────────────────────────────
-- Part 5 — Seed types, field-defs, grocery departments, aliases
-- Seeds are idempotent (guarded by NOT EXISTS) so re-applying the file is safe.
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO public.bh_list_types (name, label, icon, description, group_by, default_sort, category_set, is_seed, sort_order)
SELECT * FROM (VALUES
    ('simple',  'List',     'list',  'A simple checklist.',                              NULL,               'recent', '[]'::jsonb, true, 0),
    ('grocery', 'Grocery',  'cart',  'Groceries and household shopping, by department.', 'category',         'manual',
        '[{"key":"Produce","label":"Produce","sort_order":1},{"key":"Bakery","label":"Bakery","sort_order":2},{"key":"Deli","label":"Deli","sort_order":3},{"key":"Meat & Seafood","label":"Meat & Seafood","sort_order":4},{"key":"Dairy","label":"Dairy","sort_order":5},{"key":"Frozen","label":"Frozen","sort_order":6},{"key":"Pantry","label":"Pantry","sort_order":7},{"key":"Beverages","label":"Beverages","sort_order":8},{"key":"Snacks","label":"Snacks","sort_order":9},{"key":"Household","label":"Household","sort_order":10},{"key":"Personal Care","label":"Personal Care","sort_order":11},{"key":"Other","label":"Other","sort_order":12}]'::jsonb,
        true, 1),
    ('chores',  'Chores',   'broom', 'Household chores and tasks, by who is assigned.',   'assignee_user_id', 'due',    '[]'::jsonb, true, 2),
    ('gifts',   'Gifts',    'gift',  'Gift ideas, with recipient and link.',             NULL,               'recent', '[]'::jsonb, true, 3),
    ('todo',    'To-Do',    'check', 'General to-dos, by due date.',                     NULL,               'due',    '[]'::jsonb, true, 4),
    ('packing', 'Packing',  'bag',   'Packing lists, by section.',                       'category',         'manual', '[]'::jsonb, true, 5)
) AS v(name,label,icon,description,group_by,default_sort,category_set,is_seed,sort_order)
WHERE NOT EXISTS (SELECT 1 FROM public.bh_list_types WHERE is_seed);

-- Core field-defs (storage='column' — every list has these).
INSERT INTO public.bh_list_field_defs (scope,key,label,col_type,storage,options_source,required,groupable,sortable,filterable,sort_order)
SELECT * FROM (VALUES
    ('core','text',             'Item',     'text',          'column', NULL,     true,  false, true,  false, 1),
    ('core','checked',          'Done',     'checkbox',      'column', NULL,     false, false, true,  true,  2),
    ('core','quantity',         'Qty',      'text',          'column', NULL,     false, false, false, false, 3),
    ('core','category',         'Category', 'text',          'column', NULL,     false, true,  true,  true,  4),
    ('core','due_date',         'Due',      'date',          'column', NULL,     false, false, true,  true,  5),
    ('core','assignee_user_id', 'Assignee', 'single_select', 'column', 'users',  false, true,  false, true,  6),
    ('core','notes',            'Notes',    'text',          'column', NULL,     false, false, false, false, 7)
) AS v(scope,key,label,col_type,storage,options_source,required,groupable,sortable,filterable,sort_order)
WHERE NOT EXISTS (SELECT 1 FROM public.bh_list_field_defs WHERE scope='core');

-- Type field-defs (storage='attribute'), and type-scope overrides of core labels.
-- grocery: relabel category → "Department"; add multi-select store (from bh_stores) + price.
INSERT INTO public.bh_list_field_defs (scope,list_type_id,key,label,col_type,storage,options_source,groupable,sortable,filterable,sort_order)
SELECT 'type', t.id, v.key, v.label, v.col_type, v.storage, v.options_source, v.groupable, v.sortable, v.filterable, v.sort_order
FROM public.bh_list_types t
JOIN (VALUES
    ('grocery','category','Department','text',         'column',    NULL,     true,  true,  true,  4),
    ('grocery','store',   'Store',     'multi_select', 'attribute', 'stores', false, false, true,  8),
    ('grocery','price',   'Price',     'number',       'attribute', NULL,     false, true,  false, 9),
    ('gifts',  'recipient','Recipient','text',         'attribute', NULL,     true,  false, true,  8),
    ('gifts',  'url',     'Link',      'url',          'attribute', NULL,     false, false, false, 9),
    ('gifts',  'price',   'Price',     'number',       'attribute', NULL,     false, true,  false, 10),
    ('chores', 'priority','Priority',  'single_select','attribute', NULL,     true,  true,  true,  8),
    ('todo',   'priority','Priority',  'single_select','attribute', NULL,     true,  true,  true,  8),
    ('packing','category','Section',   'text',         'column',    NULL,     true,  true,  true,  4)
) AS v(type_name,key,label,col_type,storage,options_source,groupable,sortable,filterable,sort_order)
  ON v.type_name = t.name
WHERE NOT EXISTS (SELECT 1 FROM public.bh_list_field_defs WHERE scope='type');

-- Inline options for the priority selects (Low/Medium/High).
UPDATE public.bh_list_field_defs
   SET options = '[{"value":"low","label":"Low","sort_order":1},{"value":"medium","label":"Medium","sort_order":2},{"value":"high","label":"High","sort_order":3}]'::jsonb
 WHERE scope='type' AND key='priority' AND options IS NULL;

-- Starter grocery item→department aliases (cheap auto-categorize seed).
INSERT INTO public.bh_item_category_aliases (list_type_id, alias, department)
SELECT (SELECT id FROM public.bh_list_types WHERE name='grocery'), v.alias, v.department
FROM (VALUES
    ('milk','Dairy'),('eggs','Dairy'),('cheese','Dairy'),('butter','Dairy'),('yogurt','Dairy'),
    ('bread','Bakery'),('bagels','Bakery'),
    ('banana','Produce'),('bananas','Produce'),('apple','Produce'),('apples','Produce'),
    ('lettuce','Produce'),('spinach','Produce'),('tomato','Produce'),('tomatoes','Produce'),('onion','Produce'),
    ('chicken','Meat & Seafood'),('beef','Meat & Seafood'),('salmon','Meat & Seafood'),('ground beef','Meat & Seafood'),
    ('ice cream','Frozen'),('frozen pizza','Frozen'),
    ('rice','Pantry'),('pasta','Pantry'),('cereal','Pantry'),('flour','Pantry'),('sugar','Pantry'),
    ('coffee','Beverages'),('water','Beverages'),('juice','Beverages'),('soda','Beverages'),
    ('chips','Snacks'),('crackers','Snacks'),
    ('paper towels','Household'),('toilet paper','Household'),('dish soap','Household'),('trash bags','Household'),
    ('shampoo','Personal Care'),('toothpaste','Personal Care'),('soap','Personal Care')
) AS v(alias,department)
WHERE NOT EXISTS (
    SELECT 1 FROM public.bh_item_category_aliases
    WHERE list_type_id = (SELECT id FROM public.bh_list_types WHERE name='grocery')
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Part 6 — Backfill existing lists/items + widen kb_chunks for list embeddings
-- ─────────────────────────────────────────────────────────────────────────────
UPDATE public.bh_lists
   SET list_type_id = (SELECT id FROM public.bh_list_types WHERE name='simple')
 WHERE list_type_id IS NULL;

UPDATE public.bh_list_items i
   SET sort_order = sub.rn * 1000.0
  FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY list_id ORDER BY created_at, id) AS rn
          FROM public.bh_list_items) sub
 WHERE i.id = sub.id AND i.sort_order IS NULL;

-- Allow source_type='list' on kb_chunks (without this, every list embedding insert
-- raises check_violation and the AI-routing path is dead). DDL lives here so no
-- later migration re-opens an applied file.
ALTER TABLE public.kb_chunks DROP CONSTRAINT IF EXISTS kb_chunks_source_type_check;
ALTER TABLE public.kb_chunks ADD  CONSTRAINT kb_chunks_source_type_check
    CHECK (source_type = ANY (ARRAY['message'::text, 'entity'::text, 'list'::text]));

-- ─────────────────────────────────────────────────────────────────────────────
-- Part 7 — R2.2: dedupe colliding shared lists, then swap the uniqueness rule
-- (the dangerous step — atomic with the rest of this migration)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.bh_list_merges (
    id          serial PRIMARY KEY,
    survivor_id integer NOT NULL,
    merged_id   integer NOT NULL,
    merged_name text NOT NULL,
    item_count  integer NOT NULL,
    merged_at   timestamptz NOT NULL DEFAULT now()
);

-- Merge items of newer same-named active shared lists into the oldest (lowest id),
-- log the merge, then archive the losers (re-point, never delete).
WITH dups AS (
    SELECT id, MIN(id) OVER (PARTITION BY LOWER(name)) AS survivor_id
    FROM public.bh_lists
    WHERE is_shared AND is_archived = false
),
losers AS (
    SELECT id, survivor_id FROM dups WHERE id <> survivor_id
),
moved AS (
    UPDATE public.bh_list_items i
       SET list_id = l.survivor_id
      FROM losers l
     WHERE i.list_id = l.id
    RETURNING l.id AS loser_id
),
counts AS (
    SELECT loser_id, COUNT(*) AS c FROM moved GROUP BY loser_id
)
INSERT INTO public.bh_list_merges (survivor_id, merged_id, merged_name, item_count)
SELECT l.survivor_id, l.id, b.name, COALESCE(c.c, 0)
FROM losers l
JOIN public.bh_lists b ON b.id = l.id
LEFT JOIN counts c ON c.loser_id = l.id;

UPDATE public.bh_lists b
   SET is_archived = true,
       notes = COALESCE(b.notes, '') ||
               ' [lists-v2: merged into list #' ||
               (SELECT survivor_id FROM public.bh_list_merges m WHERE m.merged_id = b.id ORDER BY id DESC LIMIT 1) ||
               ' on 0054]'
 WHERE b.id IN (SELECT merged_id FROM public.bh_list_merges);

-- Swap the old per-(name,user_id) constraint for household-aware partial indexes.
-- Shared: case-insensitive, household-wide. Private: CASE-SENSITIVE (matches the
-- dropped constraint exactly, so it can't abort on legacy 'Todo'+'todo' pairs).
-- Both exclude archived rows so the merge losers don't collide with survivors.
ALTER TABLE public.bh_lists DROP CONSTRAINT IF EXISTS bh_lists_name_user_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_lists_shared_name
    ON public.bh_lists (LOWER(name)) WHERE is_shared AND is_archived = false;
CREATE UNIQUE INDEX IF NOT EXISTS uq_lists_private_name
    ON public.bh_lists (name, user_id) WHERE NOT is_shared AND is_archived = false;

-- ─────────────────────────────────────────────────────────────────────────────
-- Part 8 — DB-driven routing config + elected default list
-- ─────────────────────────────────────────────────────────────────────────────
-- Thresholds are PLACEHOLDERS — calibrate against the fixtured item→list set
-- (bge-m3 cosine, not the Haiku classification probability). Tunable without deploy.
INSERT INTO public.bh_platform_settings (key, value_json)
SELECT 'lists.routing', '{"match_threshold":0.55,"create_threshold":0.35,"ambiguity_margin":0.07}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM public.bh_platform_settings WHERE key='lists.routing');

-- Elect a concrete default list: legacy 'shopping' if present, else the oldest
-- active shared list, else NULL (empty install — the router lazily creates one).
INSERT INTO public.bh_platform_settings (key, value_json)
SELECT 'lists.default_list_id',
       COALESCE(
         to_jsonb((SELECT id FROM public.bh_lists
                    WHERE LOWER(name)='shopping' AND is_archived=false
                    ORDER BY is_shared DESC, id LIMIT 1)),
         to_jsonb((SELECT id FROM public.bh_lists
                    WHERE is_shared AND is_archived=false ORDER BY id LIMIT 1)),
         'null'::jsonb)
WHERE NOT EXISTS (SELECT 1 FROM public.bh_platform_settings WHERE key='lists.default_list_id');
