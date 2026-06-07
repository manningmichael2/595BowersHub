-- ============================================================================
-- 002 — File repository + multi-domain schemas
-- ============================================================================
-- Establishes the canonical file/asset model used by every domain: receipts,
-- inventory (tools, saw blades, wood, albums), house photos, cooking, manuals.
--
-- Architecture: one DB ("finance") with multiple schemas. Existing finance
-- tables stay in `public`. New domains get their own schemas. Files are stored
-- on disk; metadata + AI extraction live in `files.assets`. Domain tables
-- reference assets through link tables (never embed paths).
--
-- See steering/595bowershub-project.md → "Data Architecture / File Repository"
-- for full rationale.
--
-- Idempotent: safe to run multiple times.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Required extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

-- ---------------------------------------------------------------------------
-- Schemas
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS files;
CREATE SCHEMA IF NOT EXISTS inventory;
CREATE SCHEMA IF NOT EXISTS house;
CREATE SCHEMA IF NOT EXISTS cook;

COMMENT ON SCHEMA files     IS 'Canonical asset metadata. Every uploaded file lives here exactly once.';
COMMENT ON SCHEMA inventory IS 'Tools, saw blades, wood, albums, etc.';
COMMENT ON SCHEMA house     IS 'Room photos, future 3D map seed data.';
COMMENT ON SCHEMA cook      IS 'Recipes, cook log, finished-dish photos.';

-- ---------------------------------------------------------------------------
-- files.assets — one row per uploaded file, regardless of domain
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS files.assets (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Storage location. Currently absolute host path. Could become "s3://..." later.
    path            TEXT         NOT NULL UNIQUE,
    -- Original filename as uploaded (preserved separately so the on-disk name can be a UUID).
    original_name   TEXT,
    mime            TEXT         NOT NULL,
    size_bytes      BIGINT       NOT NULL,
    -- Hash for dedup. If the same file is dropped twice, we short-circuit.
    sha256          TEXT         NOT NULL UNIQUE,
    -- High-level domain bucket. NULL means "still in inbox / not classified yet".
    -- Allowed values are application-enforced rather than via enum so new domains
    -- can be added without a migration. Typical: receipt, tool, saw_blade, wood,
    -- album, manual, house_room, cook_recipe.
    domain          TEXT,
    uploaded_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    -- Free-form: 'michael', 'manon', 'email-receipt', 'phone-upload', etc.
    uploaded_by     TEXT,
    -- One-line human-readable summary the vision pass produces.
    ai_summary      TEXT,
    -- Structured fields the vision pass extracted. Schema varies by domain.
    ai_extracted    JSONB,
    -- e.g., 'claude-sonnet-4-5'. NULL until a vision pass runs.
    ai_model        TEXT,
    processed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS assets_domain_idx       ON files.assets (domain);
CREATE INDEX IF NOT EXISTS assets_uploaded_at_idx  ON files.assets (uploaded_at DESC);
CREATE INDEX IF NOT EXISTS assets_ai_extracted_idx ON files.assets USING gin (ai_extracted);

COMMENT ON TABLE  files.assets               IS 'Canonical record for every uploaded file across all domains.';
COMMENT ON COLUMN files.assets.path          IS 'Absolute host path today; may become object-store URI later.';
COMMENT ON COLUMN files.assets.domain        IS 'High-level bucket: receipt, tool, saw_blade, album, manual, house_room, cook_recipe, etc. NULL = unclassified/inbox.';
COMMENT ON COLUMN files.assets.ai_extracted  IS 'Domain-specific JSON from the vision pass. Shape varies by domain; consumers parse defensively.';

-- ---------------------------------------------------------------------------
-- Link table from existing finance.transactions to assets
-- (e.g., a receipt PDF/photo that produced or supports a transaction row)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.transaction_files (
    transaction_id  TEXT         NOT NULL REFERENCES public.transactions(id) ON DELETE CASCADE,
    asset_id        UUID         NOT NULL REFERENCES files.assets(id)        ON DELETE CASCADE,
    is_primary      BOOLEAN      NOT NULL DEFAULT false,
    linked_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (transaction_id, asset_id)
);

CREATE INDEX IF NOT EXISTS transaction_files_asset_idx ON public.transaction_files (asset_id);

COMMENT ON TABLE public.transaction_files IS 'Many-to-many between transactions and supporting receipt/photo files.';

-- ---------------------------------------------------------------------------
-- Inventory domain — tools, saw blades, wood, albums
-- ---------------------------------------------------------------------------
-- Skeletons only. Each gets fleshed out when its real workflow is built.
-- The shape that matters now is the link table pattern.

CREATE TABLE IF NOT EXISTS inventory.tools (
    id          BIGSERIAL    PRIMARY KEY,
    name        TEXT         NOT NULL,
    brand       TEXT,
    model       TEXT,
    type        TEXT,                   -- saw, drill, chisel, plane, etc.
    notes       TEXT,
    acquired_at DATE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS inventory.tool_files (
    tool_id     BIGINT       NOT NULL REFERENCES inventory.tools(id) ON DELETE CASCADE,
    asset_id    UUID         NOT NULL REFERENCES files.assets(id)    ON DELETE CASCADE,
    is_primary  BOOLEAN      NOT NULL DEFAULT false,
    linked_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tool_id, asset_id)
);
CREATE INDEX IF NOT EXISTS tool_files_asset_idx ON inventory.tool_files (asset_id);

CREATE TABLE IF NOT EXISTS inventory.saw_blades (
    id            BIGSERIAL    PRIMARY KEY,
    brand         TEXT,
    diameter_in   NUMERIC(5,3),
    teeth         INTEGER,
    kerf_in       NUMERIC(5,4),
    type          TEXT,                 -- rip, crosscut, combo, dado, etc.
    notes         TEXT,
    acquired_at   DATE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS inventory.saw_blade_files (
    saw_blade_id BIGINT       NOT NULL REFERENCES inventory.saw_blades(id) ON DELETE CASCADE,
    asset_id     UUID         NOT NULL REFERENCES files.assets(id)         ON DELETE CASCADE,
    is_primary   BOOLEAN      NOT NULL DEFAULT false,
    linked_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (saw_blade_id, asset_id)
);
CREATE INDEX IF NOT EXISTS saw_blade_files_asset_idx ON inventory.saw_blade_files (asset_id);

CREATE TABLE IF NOT EXISTS inventory.wood (
    id           BIGSERIAL    PRIMARY KEY,
    species      TEXT,
    dimensions   TEXT,                  -- free-form for now: "8/4 × 6\" × 48\""
    quantity     NUMERIC(6,2),
    unit         TEXT,                  -- 'board', 'bf', 'lf'
    notes        TEXT,
    acquired_at  DATE,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS inventory.wood_files (
    wood_id     BIGINT       NOT NULL REFERENCES inventory.wood(id) ON DELETE CASCADE,
    asset_id    UUID         NOT NULL REFERENCES files.assets(id)   ON DELETE CASCADE,
    is_primary  BOOLEAN      NOT NULL DEFAULT false,
    linked_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (wood_id, asset_id)
);
CREATE INDEX IF NOT EXISTS wood_files_asset_idx ON inventory.wood_files (asset_id);

CREATE TABLE IF NOT EXISTS inventory.albums (
    id              BIGSERIAL    PRIMARY KEY,
    title           TEXT         NOT NULL,
    artist          TEXT,
    label           TEXT,
    catalog_number  TEXT,
    year            INTEGER,
    condition       TEXT,
    notes           TEXT,
    last_played_at  DATE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS inventory.album_files (
    album_id    BIGINT       NOT NULL REFERENCES inventory.albums(id) ON DELETE CASCADE,
    asset_id    UUID         NOT NULL REFERENCES files.assets(id)     ON DELETE CASCADE,
    is_primary  BOOLEAN      NOT NULL DEFAULT false,
    linked_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (album_id, asset_id)
);
CREATE INDEX IF NOT EXISTS album_files_asset_idx ON inventory.album_files (asset_id);

-- ---------------------------------------------------------------------------
-- Manuals — separate concept, may attach to tools or appliances later
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inventory.manuals (
    id          BIGSERIAL    PRIMARY KEY,
    title       TEXT         NOT NULL,
    brand       TEXT,
    model       TEXT,
    doc_type    TEXT,                  -- 'manual', 'spec_sheet', 'warranty', etc.
    notes       TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS inventory.manual_files (
    manual_id   BIGINT       NOT NULL REFERENCES inventory.manuals(id) ON DELETE CASCADE,
    asset_id    UUID         NOT NULL REFERENCES files.assets(id)      ON DELETE CASCADE,
    is_primary  BOOLEAN      NOT NULL DEFAULT false,
    linked_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (manual_id, asset_id)
);
CREATE INDEX IF NOT EXISTS manual_files_asset_idx ON inventory.manual_files (asset_id);

-- ---------------------------------------------------------------------------
-- House domain — rooms, photos, future 3D map data
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS house.rooms (
    id          BIGSERIAL    PRIMARY KEY,
    name        TEXT         NOT NULL UNIQUE,    -- 'living_room', 'kitchen', 'workshop', etc.
    floor       INTEGER,
    notes       TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS house.room_files (
    room_id     BIGINT       NOT NULL REFERENCES house.rooms(id) ON DELETE CASCADE,
    asset_id    UUID         NOT NULL REFERENCES files.assets(id) ON DELETE CASCADE,
    -- Hints for future 3D reconstruction. All nullable.
    orientation TEXT,                  -- 'N', 'NE', etc., or free text
    position    TEXT,                  -- free-form for now
    is_primary  BOOLEAN      NOT NULL DEFAULT false,
    linked_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (room_id, asset_id)
);
CREATE INDEX IF NOT EXISTS room_files_asset_idx ON house.room_files (asset_id);

-- ---------------------------------------------------------------------------
-- Cook domain — recipes and finished-dish photos
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cook.recipes (
    id              BIGSERIAL    PRIMARY KEY,
    title           TEXT         NOT NULL,
    slug            TEXT         UNIQUE,
    source          TEXT,
    servings        INTEGER,
    calories_each   INTEGER,
    notes           TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cook.recipe_files (
    recipe_id   BIGINT       NOT NULL REFERENCES cook.recipes(id) ON DELETE CASCADE,
    asset_id    UUID         NOT NULL REFERENCES files.assets(id)  ON DELETE CASCADE,
    file_role   TEXT,                  -- 'source_page', 'finished_dish', 'in_progress'
    is_primary  BOOLEAN      NOT NULL DEFAULT false,
    linked_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (recipe_id, asset_id)
);
CREATE INDEX IF NOT EXISTS recipe_files_asset_idx ON cook.recipe_files (asset_id);

CREATE TABLE IF NOT EXISTS cook.cook_log (
    id            BIGSERIAL    PRIMARY KEY,
    recipe_id     BIGINT       NOT NULL REFERENCES cook.recipes(id) ON DELETE CASCADE,
    cooked_at     DATE         NOT NULL DEFAULT CURRENT_DATE,
    servings_made INTEGER,
    adjustments   TEXT,
    rating        SMALLINT,            -- 1..5 if you want
    notes         TEXT,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Read-only finance user (already exists per steering) — grant read on new schemas
-- so the existing finance-query workflow can answer cross-domain questions.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'finance_reader') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA files, inventory, house, cook TO finance_reader';
        EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA files     TO finance_reader';
        EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA inventory TO finance_reader';
        EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA house     TO finance_reader';
        EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA cook      TO finance_reader';
        EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA files     GRANT SELECT ON TABLES TO finance_reader';
        EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA inventory GRANT SELECT ON TABLES TO finance_reader';
        EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA house     GRANT SELECT ON TABLES TO finance_reader';
        EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA cook      GRANT SELECT ON TABLES TO finance_reader';
    END IF;
END $$;
