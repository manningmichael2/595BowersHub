-- ============================================================================
-- 005 — Add archived_at + updated_at to all inventory tables for admin skill
-- ============================================================================
-- The inventory_admin workflow needs:
--   - archived_at (TIMESTAMPTZ, nullable) for soft-delete
--   - updated_at  (TIMESTAMPTZ, NOT NULL DEFAULT now()) for update tracking
--
-- tools already has updated_at. All others need both or one.
-- Idempotent: uses IF NOT EXISTS pattern via DO blocks.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- inventory.tools — add archived_at only (already has updated_at)
-- ---------------------------------------------------------------------------
ALTER TABLE inventory.tools ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

-- ---------------------------------------------------------------------------
-- inventory.saw_blades — add both
-- ---------------------------------------------------------------------------
ALTER TABLE inventory.saw_blades ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE inventory.saw_blades ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

-- ---------------------------------------------------------------------------
-- inventory.wood — add both
-- ---------------------------------------------------------------------------
ALTER TABLE inventory.wood ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE inventory.wood ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

-- ---------------------------------------------------------------------------
-- inventory.albums — add both
-- ---------------------------------------------------------------------------
ALTER TABLE inventory.albums ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE inventory.albums ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

-- ---------------------------------------------------------------------------
-- inventory.manuals — add both
-- ---------------------------------------------------------------------------
ALTER TABLE inventory.manuals ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE inventory.manuals ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

-- ---------------------------------------------------------------------------
-- Grant SELECT on new columns to finance_reader (already has table-level SELECT
-- from migration 002, but ALTER DEFAULT PRIVILEGES ensures future tables too)
-- ---------------------------------------------------------------------------
-- No action needed — column-level grants aren't required when table-level
-- SELECT is already granted. The existing GRANT SELECT ON ALL TABLES covers it.
