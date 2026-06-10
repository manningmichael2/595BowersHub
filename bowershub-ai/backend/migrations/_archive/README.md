# Archived migrations (pre-baseline)

These are the original granular migrations (001–022) that built the schema
before it was squashed into `../0001_baseline.sql` (project-review.md C2).

They are kept for historical reference only. **They are NOT applied** —
`run_migrations()` scans only top-level `*.sql` files in `backend/migrations/`,
so this subdirectory is ignored. The live database already has these recorded
in `bh_migrations`; new/empty databases build from the baseline instead.

Do not edit or re-add these to the active directory. New schema changes go in
forward-only `0002_*.sql`, `0003_*.sql`, … alongside the baseline.
