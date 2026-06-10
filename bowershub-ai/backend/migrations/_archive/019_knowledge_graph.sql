-- Migration 019: Knowledge Graph — structured memory replacing markdown grep
--
-- Two core tables:
--   bh_entities     — people, places, things, concepts, facts
--   bh_relationships — connections between entities
--
-- Design principles:
--   - Entities have a type (person, place, thing, fact, event, preference, recipe, tool, etc.)
--   - Attributes are JSONB (flexible, schema-free per entity type)
--   - Relationships are directional with a type label
--   - Everything is timestamped for history
--   - The AI can query this via ask-db naturally (it's just SQL)
--   - Old markdown knowledge base stays as-is (archive, still searchable via recall)

CREATE TABLE IF NOT EXISTS public.bh_entities (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    entity_type TEXT NOT NULL,  -- person, place, thing, fact, event, preference, recipe, tool, concept, note
    summary     TEXT,            -- one-line description
    attributes  JSONB NOT NULL DEFAULT '{}',  -- flexible key-value (allergies, birthday, brand, etc.)
    source      TEXT,            -- where this knowledge came from (chat, manual, import)
    confidence  NUMERIC(3,2) DEFAULT 1.0,  -- 0-1, how confident we are (1.0 = user stated, 0.7 = inferred)
    is_active   BOOLEAN NOT NULL DEFAULT true,  -- soft delete / superseded
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by  INTEGER REFERENCES public.bh_users(id)
);

-- Full-text search on name + summary
CREATE INDEX IF NOT EXISTS idx_entities_fts
    ON public.bh_entities USING gin(to_tsvector('english', name || ' ' || COALESCE(summary, '')));

-- Type-based lookups
CREATE INDEX IF NOT EXISTS idx_entities_type ON public.bh_entities(entity_type);

-- JSONB attribute search
CREATE INDEX IF NOT EXISTS idx_entities_attributes ON public.bh_entities USING gin(attributes);

-- Name lookup (case-insensitive)
CREATE INDEX IF NOT EXISTS idx_entities_name_lower ON public.bh_entities(LOWER(name));


CREATE TABLE IF NOT EXISTS public.bh_relationships (
    id              SERIAL PRIMARY KEY,
    from_entity_id  INTEGER NOT NULL REFERENCES public.bh_entities(id) ON DELETE CASCADE,
    to_entity_id    INTEGER NOT NULL REFERENCES public.bh_entities(id) ON DELETE CASCADE,
    relationship    TEXT NOT NULL,  -- "allergic_to", "likes", "owns", "made_on", "lives_at", "related_to", etc.
    attributes      JSONB DEFAULT '{}',  -- metadata about the relationship (since, strength, context)
    source          TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Prevent exact duplicate relationships
    UNIQUE (from_entity_id, to_entity_id, relationship)
);

CREATE INDEX IF NOT EXISTS idx_relationships_from ON public.bh_relationships(from_entity_id);
CREATE INDEX IF NOT EXISTS idx_relationships_to ON public.bh_relationships(to_entity_id);
CREATE INDEX IF NOT EXISTS idx_relationships_type ON public.bh_relationships(relationship);


-- Seed some initial entities from what we know is already in the knowledge base
INSERT INTO public.bh_entities (name, entity_type, summary, attributes, source) VALUES
    ('Michael', 'person', 'Owner of BowersHub AI. Hobbyist woodworker, tech enthusiast.', '{"role": "owner", "email": "manningmichael2@gmail.com"}', 'system'),
    ('Manon', 'person', 'Michael''s girlfriend. Shares cooking workspace.', '{}', 'system'),
    ('595BowersHub', 'place', 'Home server — Minisforum mini PC running all services.', '{"ip": "100.106.180.101", "os": "Ubuntu 26.04"}', 'system'),
    ('BowersHub AI', 'thing', 'Custom AI chat app (this system).', '{"url": "https://595bowershub.tailc4d58a.ts.net", "stack": "FastAPI + React + Postgres"}', 'system')
ON CONFLICT DO NOTHING;

-- Create some relationships
INSERT INTO public.bh_relationships (from_entity_id, to_entity_id, relationship, source)
SELECT m.id, mn.id, 'partner_of', 'system'
FROM public.bh_entities m, public.bh_entities mn
WHERE m.name = 'Michael' AND mn.name = 'Manon'
AND NOT EXISTS (
    SELECT 1 FROM public.bh_relationships 
    WHERE from_entity_id = m.id AND to_entity_id = mn.id AND relationship = 'partner_of'
);

INSERT INTO public.bh_relationships (from_entity_id, to_entity_id, relationship, source)
SELECT m.id, bh.id, 'owns', 'system'
FROM public.bh_entities m, public.bh_entities bh
WHERE m.name = 'Michael' AND bh.name = '595BowersHub'
AND NOT EXISTS (
    SELECT 1 FROM public.bh_relationships 
    WHERE from_entity_id = m.id AND to_entity_id = bh.id AND relationship = 'owns'
);
