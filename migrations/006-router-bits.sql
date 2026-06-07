-- ============================================================================
-- 006 — Router bits table + file link table
-- ============================================================================
-- New table: inventory.router_bits
-- Stores individual router bits with profile, dimensions, bearing info.
-- Follows the same pattern as inventory.tools, inventory.saw_blades, etc.
--
-- Idempotent: safe to run multiple times.
-- ============================================================================

CREATE TABLE IF NOT EXISTS inventory.router_bits (
    id                      BIGSERIAL    PRIMARY KEY,
    brand                   TEXT,
    profile                 TEXT         NOT NULL,      -- e.g., 'Cove', 'Round Over', 'Flush Trim'
    shank_size_in           NUMERIC(4,3),              -- 0.25 or 0.5 typically
    cutting_diameter_in     NUMERIC(5,3),
    cutting_length_in       NUMERIC(5,3),
    radius_in               NUMERIC(5,3),              -- radius of the profile cut
    angle_deg               NUMERIC(5,1),              -- angle for chamfer/bevel bits
    has_bearing             BOOLEAN,
    set_name                TEXT,                       -- model number or set identifier
    model_number            TEXT,                       -- manufacturer catalog/model number
    notes                   TEXT,
    condition               TEXT,                       -- 'new', 'good', 'worn', 'damaged'
    purchase_price          NUMERIC(8,2),
    current_value_estimate  NUMERIC(8,2),
    value_estimated_at      DATE,
    acquired_at             DATE,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
    archived_at             TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS inventory.router_bit_files (
    router_bit_id  BIGINT  NOT NULL REFERENCES inventory.router_bits(id) ON DELETE CASCADE,
    asset_id       UUID    NOT NULL REFERENCES files.assets(id)          ON DELETE CASCADE,
    is_primary     BOOLEAN NOT NULL DEFAULT false,
    linked_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (router_bit_id, asset_id)
);

CREATE INDEX IF NOT EXISTS router_bit_files_asset_idx ON inventory.router_bit_files (asset_id);

-- Grant read access to finance_reader if it exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'finance_reader') THEN
        EXECUTE 'GRANT SELECT ON inventory.router_bits TO finance_reader';
        EXECUTE 'GRANT SELECT ON inventory.router_bit_files TO finance_reader';
    END IF;
END $$;

COMMENT ON TABLE inventory.router_bits IS 'Individual router bits — profile, dimensions, bearing, brand/model info.';
COMMENT ON TABLE inventory.router_bit_files IS 'Link table: router bits to files.assets (photos, manuals).';
