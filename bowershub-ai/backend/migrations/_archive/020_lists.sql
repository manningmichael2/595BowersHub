-- Migration 020: Lists — shopping lists, to-do lists, packing lists, etc.
-- Items have a checked/unchecked state. AI can add, check off, and remove items.
-- Visible in DB Admin for manual management.

CREATE TABLE IF NOT EXISTS public.bh_lists (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    user_id     INTEGER NOT NULL REFERENCES public.bh_users(id) ON DELETE CASCADE,
    description TEXT,
    is_archived BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (name, user_id)
);

CREATE TABLE IF NOT EXISTS public.bh_list_items (
    id          SERIAL PRIMARY KEY,
    list_id     INTEGER NOT NULL REFERENCES public.bh_lists(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    checked     BOOLEAN NOT NULL DEFAULT false,
    quantity    TEXT,            -- "2 lbs", "1 dozen", etc. (optional)
    notes       TEXT,            -- extra context
    added_by    TEXT DEFAULT 'chat',  -- 'chat', 'manual', 'voice'
    checked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_list_items_list ON public.bh_list_items(list_id);
CREATE INDEX IF NOT EXISTS idx_lists_user ON public.bh_lists(user_id);

-- Seed a shopping list for Michael (user_id = 1)
INSERT INTO public.bh_lists (name, user_id, description)
VALUES ('shopping', 1, 'Grocery and household shopping list')
ON CONFLICT (name, user_id) DO NOTHING;
