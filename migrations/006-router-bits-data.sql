-- Migrate 23 router bits from /knowledge/woodshop/router-bits.md into inventory.router_bits
-- Run AFTER 006-router-bits.sql. Idempotent check: skip if table already has rows.
DO $$
BEGIN
  IF (SELECT count(*) FROM inventory.router_bits) > 0 THEN
    RAISE NOTICE 'router_bits already has data — skipping seed.';
    RETURN;
  END IF;

  INSERT INTO inventory.router_bits (brand, profile, shank_size_in, cutting_diameter_in, cutting_length_in, has_bearing, set_name, notes) VALUES
  ('Rockler', 'Mini Cabinet Door', 0.5, NULL, NULL, NULL, 'Mini Cabinet Door Set', NULL),
  ('Woodline', 'Unknown', 0.5, NULL, NULL, NULL, 'WL-1225-4', NULL),
  ('Woodline', 'Slot Cutter', 0.5, 0.5, NULL, NULL, NULL, NULL),
  ('Woodtek', 'Unknown', 0.5, NULL, NULL, NULL, '819647', NULL),
  ('Woodline', 'Tongue & Groove (tongue)', 0.5, 1.5, 1.375, NULL, 'WL-1338-5.5 (2pc set)', '1/4" slot, 3/8" x 1/4" tooth, Woodline USA'),
  ('Woodline', 'Tongue & Groove (groove)', 0.5, 1.5, 1.375, NULL, 'WL-1338-5.5 (2pc set)', '1/4" slot, 3/8" x 1/4" tooth, Woodline USA'),
  ('MLCS', 'Raised Panel', 0.5, NULL, NULL, NULL, '#18698', NULL),
  (NULL, '45° Chamfer', 0.5, NULL, NULL, NULL, NULL, NULL),
  ('Woodline', 'Finger Pull', 0.5, NULL, NULL, NULL, NULL, NULL),
  ('Woodline', 'Ogee', 0.5, NULL, NULL, NULL, 'WL-1262', NULL),
  (NULL, 'Round Over', 0.5, 0.625, NULL, NULL, NULL, '5/8 inch radius'),
  (NULL, 'Cove', 0.5, 0.125, NULL, NULL, NULL, '1/8 inch radius'),
  (NULL, 'Cove', 0.5, 0.25, NULL, NULL, NULL, '1/4 inch radius'),
  ('Woodtek', 'Cove', 0.5, 0.375, NULL, NULL, '820165', '3/8 inch radius'),
  (NULL, 'Cove', 0.5, 0.5, NULL, NULL, NULL, '1/2 inch radius'),
  (NULL, 'Cove', 0.5, 0.625, NULL, NULL, NULL, '5/8 inch radius'),
  (NULL, 'Cove', 0.5, 0.75, NULL, NULL, NULL, '3/4 inch radius'),
  (NULL, 'Bowl', 0.5, 0.25, NULL, NULL, NULL, '1/4 inch radius'),
  ('Woodline', 'Roundover', 0.5, 1.5, NULL, NULL, 'WL-6851 Glass Panel Door', 'Glass Panel Door bit, 3/8" radius roundover profile, 1-1/2" overall cutter diameter'),
  (NULL, 'Flush Trim Laminate', 0.25, NULL, NULL, false, NULL, 'Straight profile, no bearing'),
  (NULL, 'Flush Trim Laminate', 0.25, NULL, NULL, false, NULL, 'Beveled profile, no bearing'),
  (NULL, 'Beveled Flush Trim', 0.25, NULL, NULL, true, NULL, 'With bearing'),
  (NULL, 'Straight Flush Trim', 0.25, NULL, NULL, true, NULL, 'With bearing');

  RAISE NOTICE 'Inserted 23 router bits.';
END $$;
