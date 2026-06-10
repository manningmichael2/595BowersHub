# Implementation Plan: Native DB Browser

## Overview

Replace the standalone Flask-based DB Admin app with a native React-based database browser built into BowersHub AI. The implementation progresses from database migrations and backend API through frontend components, with property-based tests validating correctness alongside each implementation wave.

## Tasks

- [x] 1. Database migrations and backend foundation
  - [x] 1.1 Create database migration for `bh_db_browser_layouts` table
    - Create migration SQL file with the table definition, unique constraint, and index
    - Include `id`, `user_id`, `schema_name`, `table_name`, `list_config` (JSONB), `detail_config` (JSONB), `updated_at`
    - _Requirements: 10.5, 24.2_

  - [x] 1.2 Create database migration for `bh_db_browser_views` table
    - Create migration SQL with UUID primary key, user_id FK, schema/table/name/config columns
    - Add composite index on (user_id, schema_name, table_name)
    - _Requirements: 28.4, 28.6_

  - [x] 1.3 Create database migration for `bh_db_browser_undo_log` table
    - Create migration SQL with session_id UUID, operation_type CHECK constraint, previous_values/new_values JSONB
    - Add indexes on (session_id, created_at DESC) and (session_id, is_undone)
    - _Requirements: 29.6_

  - [x] 1.4 Create the FastAPI router skeleton at `backend/routers/db_browser.py`
    - Set up the router with `/api/db` prefix
    - Add JWT auth dependency (`get_current_user`) and admin guard (`require_admin`)
    - Register the router in `backend/main.py`
    - Include asyncpg pool access pattern matching existing routers
    - _Requirements: 21.1, 21.2, 21.4_

- [x] 2. Schema introspection and core CRUD API endpoints
  - [x] 2.1 Implement `GET /api/db/schemas` endpoint
    - Query `information_schema` for all user schemas (exclude pg_*, information_schema)
    - Return schemas with tables, column counts, row counts, and link-table presence (parallel queries)
    - _Requirements: 2.1, 2.3, 2.4_

  - [x] 2.2 Implement `GET /api/db/:schema/:table/columns` and `GET /api/db/:schema/:table/pk` endpoints
    - Return column metadata (name, type, nullable, default, FK info) from information_schema
    - Return primary key column(s) for the table
    - _Requirements: 3.1, 7.4_

  - [x] 2.3 Implement `GET /api/db/:schema/:table/rows` with pagination, sort, filter, search
    - Accept query params: page, page_size, sort_column, sort_direction, filters (JSON), search
    - Build dynamic SQL with parameterized queries for safety
    - Return rows, total_rows, filtered_rows, page, page_size
    - Implement server-side sorting with nulls-last behavior
    - Implement AND-combined filter predicates (eq, neq, contains, gt, lt, is_null, has_value)
    - Implement cross-column text search with ILIKE on text/varchar columns
    - _Requirements: 3.1, 4.5, 5.3, 5.5, 6.2_

  - [x] 2.4 Implement `GET /api/db/:schema/:table/rows/:id` endpoint
    - Fetch single row by primary key value
    - _Requirements: 7.1_

  - [x] 2.5 Implement `POST /api/db/:schema/:table/rows` (create row)
    - Accept JSON body with field values, insert row, return new row with generated PK
    - Translate constraint violations to human-readable errors
    - _Requirements: 12.3, 12.4_

  - [x] 2.6 Implement `PATCH /api/db/:schema/:table/rows/:id` (update row)
    - Accept partial field updates, apply via UPDATE, return updated row
    - Translate constraint violations to human-readable errors
    - Write undo log entry (previous values) when X-DB-Session-Id header is present
    - _Requirements: 7.2, 7.3, 29.6_

  - [x] 2.7 Implement `DELETE /api/db/:schema/:table/rows/:id` (delete row)
    - Hard delete row, write undo log entry with full previous row state
    - _Requirements: 27.4_

  - [x] 2.8 Write property tests for pagination invariants (Python/Hypothesis)
    - **Property 2: Pagination invariants**
    - Test that rows.length <= pageSize, totalPages == ceil(totalRows / pageSize), offset == (page - 1) * pageSize
    - **Validates: Requirements 3.1, 3.3**

  - [x] 2.9 Write property tests for sort ordering correctness (Python/Hypothesis)
    - **Property 3: Sort ordering correctness**
    - Test ascending/descending ordering with nulls-last for arbitrary column types
    - **Validates: Requirements 4.1, 4.5**

  - [x] 2.10 Write property tests for filter predicate satisfaction (Python/Hypothesis)
    - **Property 4: Filter predicate satisfaction**
    - Test that every returned row satisfies all applied filter conditions
    - **Validates: Requirements 5.2, 5.3, 5.5**

  - [x] 2.11 Write property test for text search inclusion (Python/Hypothesis)
    - **Property 5: Text search inclusion**
    - Test that every returned row has at least one text column containing the search term
    - **Validates: Requirements 6.2, 6.5**

- [x] 3. Checkpoint - Backend core API
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Frontend foundation — store, routing, page shell
  - [x] 4.1 Create the Zustand store at `frontend/src/stores/db-browser.ts`
    - Define full state shape: schemas, activeSchema/Table, columns, rows, pagination, sort, filters, search, activeRow, dirtyFields, layouts, fieldHints, editingCell, focusedCell, selectedRows, views, activeViewId, undoStack, redoStack, sessionId
    - Implement core actions: loadSchemas, selectTable, loadRows, setPage, setPageSize, setSort, setFilters, setSearch
    - Implement detail actions: loadRow, saveRow, createRow, deleteRow
    - Implement field hints: loadFieldHints
    - _Requirements: 1.1, 2.1, 3.1, 7.2_

  - [x] 4.2 Set up React Router routes for `/db`, `/db/:schema/:table`, `/db/:schema/:table/:id`
    - Add lazy-loaded route in App.tsx with `React.lazy`
    - Create `DbBrowserPage.tsx` as the top-level layout (sidebar + content area)
    - _Requirements: 1.1, 1.2, 1.5_

  - [x] 4.3 Create `WelcomeState.tsx` component
    - Display schema/table counts and quick links to recently viewed tables
    - Shown when navigating to `/db` without a table selected
    - _Requirements: 1.4_

- [x] 5. Core UI components — SchemaSidebar and TableView
  - [x] 5.1 Implement `SchemaSidebar.tsx`
    - Display schemas as collapsible groups with tables listed alphabetically
    - Indicate tables with image support (link table) via icon
    - Highlight active table, navigate on click
    - Collapsible to overlay drawer on mobile (< 640px viewport)
    - _Requirements: 2.2, 2.4, 2.5, 23.1_

  - [x] 5.2 Implement `TableView.tsx` with paginated rows
    - Render rows in a scrollable table with column headers
    - Support horizontal scroll on narrow viewports
    - Display pagination controls (current page, total pages, page size selector: 25, 50, 100)
    - Show thumbnail previews for tables with image support
    - Navigate to DetailView on row click
    - _Requirements: 3.2, 3.3, 3.4, 3.5, 23.2_

  - [x] 5.3 Implement column sorting in TableView
    - Click header → ascending → descending → clear (3-state cycle)
    - Display sort direction arrow indicator on sorted column
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 5.4 Implement `FilterBuilder.tsx` component
    - Multi-condition filter UI with add/remove conditions
    - Support operators: equals, not equals, contains, greater than, less than, is null, has value
    - Display active filter count badge on filter button
    - _Requirements: 5.1, 5.2, 5.4_

  - [x] 5.5 Implement text search in TableView
    - Search input with 300ms debounce
    - Display matched row count when search is active
    - Combine with column filters simultaneously
    - _Requirements: 6.1, 6.3, 6.4, 6.5_

  - [x] 5.6 Write property test for sidebar alphabetical ordering (TypeScript/fast-check)
    - **Property 1: Sidebar tables are alphabetically sorted within each schema**
    - Test that for any set of table names, the sort function produces lexicographic order
    - **Validates: Requirements 2.2**

- [x] 6. Detail View and Smart Field Rendering
  - [x] 6.1 Implement `DetailView.tsx`
    - Display all editable columns in a form layout
    - Show read-only fields (PK, created_at, updated_at) with visual distinction
    - Navigation buttons for previous/next row (respecting filters/sort)
    - Save button that PATCHes only dirty fields
    - _Requirements: 7.1, 7.4, 7.5_

  - [x] 6.2 Implement `SmartFieldRenderer.tsx` with resolution logic
    - Priority chain: Field_Hint → FK constraint → Postgres type fallback
    - Support `compact` prop for inline mode vs full mode
    - Map data types to default widgets per the design's type-to-widget table
    - _Requirements: 8.1, 24.1, 24.3_

  - [x] 6.3 Implement field components: `TextField`, `NumberField`, `BooleanField`, `DateField`, `UrlField`, `TextareaField`, `SelectField`
    - TextField for text/varchar, NumberField for numeric types with prefix/suffix
    - BooleanField as Yes/No toggle, DateField with native date picker
    - UrlField with clickable link icon, TextareaField as resizable textarea
    - SelectField for dropdown with static options (condition, etc.)
    - _Requirements: 8.2, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9_

  - [x] 6.4 Implement `FractionField.tsx`
    - Display decimal as fraction string (e.g., 0.375 → "3/8\"")
    - Accept fraction or decimal input, store as decimal
    - Use lookup table for common woodworking fractions (1/64 through 63/64)
    - _Requirements: 8.3_

  - [x] 6.5 Implement `LookupField.tsx` (FK dropdown with type-ahead)
    - Populate from referenced table using lookup-options endpoint
    - Display human-readable label (name/title/description priority)
    - Hyperlink icon to navigate to linked record
    - Type-ahead search for tables with >200 rows
    - _Requirements: 8.10, 17.1, 17.2, 17.3, 17.5_

  - [x] 6.6 Implement `GET /api/db/:schema/:table/lookup-options/:column` endpoint
    - Return id + display label for FK dropdown
    - Support `?search=` parameter for type-ahead filtering
    - _Requirements: 17.4, 17.5_

  - [x] 6.7 Write property tests for smart field resolution (TypeScript/fast-check)
    - **Property 6: Smart field hint resolution**
    - **Property 8: Type-based fallback rendering**
    - Test that field hints override type defaults, and types map correctly when no hints exist
    - **Validates: Requirements 8.1, 24.1, 24.3**

  - [x] 6.8 Write property test for fraction round-trip (TypeScript/fast-check)
    - **Property 7: Fraction round-trip conversion**
    - Test that converting decimal → display → parse produces the original value for fractions with denominator ≤ 64
    - **Validates: Requirements 8.3**

  - [x] 6.9 Write property test for lookup display column selection (TypeScript/fast-check)
    - **Property 11: Lookup display column selection**
    - Test that the selection algorithm picks name → title → description → first text column
    - **Validates: Requirements 17.2**

- [x] 7. Checkpoint - Core UI functional
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Image management
  - [x] 8.1 Implement image management API endpoints
    - `GET /api/db/:schema/:table/rows/:id/images` — get linked images
    - `POST /api/db/:schema/:table/rows/:id/images` — upload and link
    - `PUT /api/db/:schema/:table/rows/:id/images/reorder` — reorder
    - `PUT /api/db/:schema/:table/rows/:id/images/:asset_id/primary` — set primary
    - `DELETE /api/db/:schema/:table/rows/:id/images/:asset_id` — unlink
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 8.2 Implement `ImageGallery.tsx` component
    - Display linked photos as thumbnails
    - Upload via file picker or drag-and-drop
    - Reorder via drag-and-drop
    - Set primary image (star icon)
    - Unlink image (remove link table row, not the file)
    - Full-size preview overlay on thumbnail tap
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

- [x] 9. Layout customization
  - [x] 9.1 Implement layout API endpoints
    - `GET /api/db/layouts/:schema/:table` — get per-table layout config
    - `PUT /api/db/layouts/:schema/:table` — save layout config
    - _Requirements: 10.5_

  - [x] 9.2 Implement `LayoutSettings.tsx` for detail view customization
    - Gear icon toggle for settings panel
    - Drag-and-drop field reordering
    - Toggle field visibility
    - Set field width (25%, 33%, 50%, 100%)
    - Set field height (small, medium, large)
    - Default: all columns, 50% width, database column order
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.6_

  - [x] 9.3 Implement `ColumnSettings.tsx` for list view column customization
    - Gear icon toggle for column panel
    - Toggle column visibility and reorder
    - Always show PK column regardless of settings
    - Default: hide wide columns (notes, URLs), show rest in DB order
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [x] 9.4 Write property test for layout configuration round-trip (TypeScript/fast-check)
    - **Property 10: Layout configuration round-trip**
    - Test that saving and retrieving a layout config returns an equivalent object
    - **Validates: Requirements 10.5, 24.2**

- [x] 10. Row creation and duplication
  - [x] 10.1 Implement `CreateRowDialog.tsx`
    - "Add Row" button opens creation form using SmartFieldRenderer
    - Pre-populate with column defaults where defined
    - Navigate to DetailView on successful creation
    - _Requirements: 12.1, 12.2, 12.5_

  - [x] 10.2 Implement row duplication in DetailView
    - "Duplicate" button copies all fields except PK and timestamps
    - Open creation form with pre-filled values for modification before saving
    - _Requirements: 13.1, 13.2, 13.3_

  - [x] 10.3 Write property test for duplicate row field preservation (TypeScript/fast-check)
    - **Property 9: Duplicate row field preservation**
    - Test that duplicating a row preserves all fields except PK and timestamp columns
    - **Validates: Requirements 13.1, 13.3**

- [x] 11. Schema management (DDL operations)
  - [x] 11.1 Implement DDL API endpoints
    - `POST /api/db/schemas` — create schema
    - `POST /api/db/tables` — create table with optional link table
    - `PATCH /api/db/tables/:schema/:table` — rename, move schema, add/drop column
    - `POST /api/db/tables/:schema/:table/preview` — SQL preview
    - _Requirements: 14.6, 15.2, 15.3, 16.2, 16.3, 16.4, 16.5_

  - [x] 11.2 Implement `CreateTableDialog.tsx`
    - Schema selector, table name input, dynamic column builder
    - Column: name, type (text, integer, decimal, boolean, date, timestamp, lookup), nullable, default
    - Live SQL preview of CREATE TABLE statement
    - "Include image support" checkbox for auto-creating link table
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_

  - [x] 11.3 Implement schema/table context menu actions in SchemaSidebar
    - "New Schema" action with name input
    - "New Table" action opening CreateTableDialog
    - Context menu on tables: Rename, Move to Schema, Add Column, Delete Column
    - _Requirements: 15.1, 16.1_

- [x] 12. Checkpoint - Full CRUD and schema management
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Field properties settings
  - [x] 13.1 Implement field hints API endpoints
    - `GET /api/db/field-hints` — return all field hint records
    - `PUT /api/db/field-hints/:column_name` — upsert field hint
    - `DELETE /api/db/field-hints/:column_name` — delete field hint
    - _Requirements: 18.4_

  - [x] 13.2 Implement `FieldSettingsPage.tsx`
    - List all columns across all user schemas with current Field_Hint configuration
    - Allow setting: input type, prefix, suffix, min/max/step, placeholder, dropdown options
    - Filter by All, Configured, Unconfigured states
    - Search by column name
    - Immediate effect on SmartFieldRenderer without page reload
    - _Requirements: 18.1, 18.2, 18.3, 18.5, 18.6_

  - [x] 13.3 Write property test for field hint round-trip (TypeScript/fast-check)
    - **Property 12: Field hint round-trip**
    - Test that saving and retrieving a field hint returns the same configuration
    - **Validates: Requirements 18.4, 18.5**

- [x] 14. Inline cell editing
  - [x] 14.1 Implement inline editing store actions and `InlineCellEditor.tsx`
    - `startEditing`, `stopEditing`, `saveCellValue` actions in store
    - Mount SmartFieldRenderer in compact mode within the cell
    - Save on blur (PATCH immediately)
    - Enter: save + move focus down
    - Tab: save + move focus to next editable cell
    - Escape: discard changes, return to static display
    - Revert on constraint violation + toast error
    - _Requirements: 25.1, 25.2, 25.3, 25.4, 25.5, 25.6_

  - [x] 14.2 Write property test for inline edit save persistence (Python/Hypothesis)
    - **Property 13: Inline edit save persistence**
    - Test that after PATCH, re-fetching the row returns the updated value
    - **Validates: Requirements 25.5**

- [x] 15. Keyboard navigation
  - [x] 15.1 Implement `KeyboardNavigationProvider.tsx` and `useKeyboardNavigation.ts`
    - Track focusedCell state with visual focus ring (CSS outline)
    - Arrow keys move focus within grid bounds (when not in edit mode)
    - Enter activates editing on focused cell
    - Tab/Shift+Tab moves to next/previous editable cell, wrapping at row boundaries
    - Ctrl+N opens CreateRowDialog
    - Ctrl+D duplicates focused row
    - Ctrl+F focuses search input
    - Delete opens deletion confirmation
    - Detect editable cells (exclude PK, timestamps)
    - _Requirements: 26.1, 26.2, 26.3, 26.4, 26.5, 26.6, 26.7_

- [x] 16. Bulk operations
  - [x] 16.1 Implement bulk API endpoints
    - `POST /api/db/:schema/:table/bulk-delete` — delete multiple rows by IDs, write undo log entries
    - `POST /api/db/:schema/:table/bulk-edit` — update single field on multiple rows, write undo log entries
    - _Requirements: 27.4, 27.5_

  - [x] 16.2 Implement selection model and `BulkActionsToolbar.tsx`
    - Checkbox column for row selection
    - Shift+click range selection
    - Header checkbox for select all/none (indeterminate state)
    - Toolbar with count + Delete, Edit Field, Export CSV buttons
    - _Requirements: 27.1, 27.2, 27.3_

  - [x] 16.3 Implement `BulkEditDialog.tsx`
    - Column picker (excluding PK/timestamps)
    - SmartFieldRenderer for the selected column to set value
    - Apply to all selected rows
    - _Requirements: 27.5_

  - [x] 16.4 Implement bulk delete with confirmation dialog
    - Show exact count of rows to be deleted
    - On confirmation, call bulk-delete endpoint
    - _Requirements: 27.4_

  - [x] 16.5 Implement bulk export CSV (selected rows only)
    - Generate and download CSV file with visible columns for selected rows
    - _Requirements: 27.6_

  - [x] 16.6 Write property test for bulk edit consistency (Python/Hypothesis)
    - **Property 14: Bulk edit consistency**
    - Test that after bulk edit, all affected rows have the target field set to the specified value
    - **Validates: Requirements 27.5**

- [x] 17. Checkpoint - Inline editing and bulk ops
  - Ensure all tests pass, ask the user if questions arise.

- [x] 18. Saved views
  - [x] 18.1 Implement saved views API endpoints
    - `GET /api/db/views/:schema/:table` — list views for current user + table
    - `POST /api/db/views/:schema/:table` — create new view
    - `PATCH /api/db/views/:schema/:table/:view_id` — rename view
    - `DELETE /api/db/views/:schema/:table/:view_id` — delete view
    - _Requirements: 28.4, 28.5_

  - [x] 18.2 Implement `SavedViewTabs.tsx`
    - Tab bar above table with "All" (default, undeletable) + saved view tabs
    - Clicking a tab applies stored filters, sort, and column visibility
    - "Save View" prompts for name, persists current config
    - Context menu on tabs for Rename and Delete
    - _Requirements: 28.1, 28.2, 28.3, 28.5_

  - [x] 18.3 Write property test for saved view filter application (Python/Hypothesis)
    - **Property 17: Saved view filter application**
    - Test that activating a view produces the same result as manually applying its filters/sort
    - **Validates: Requirements 28.3**

- [x] 19. Undo/Redo system
  - [x] 19.1 Implement undo/redo API endpoints
    - `POST /api/db/undo` — undo last operation for current session (read X-DB-Session-Id header)
    - `POST /api/db/redo` — redo last undone operation
    - `POST /api/db/undo/clear-session` — clear session undo log
    - _Requirements: 29.1, 29.5, 29.7_

  - [x] 19.2 Implement `UndoRedoProvider.tsx` and `useUndoRedo.ts`
    - Generate session UUID on mount
    - Send X-DB-Session-Id header with every write request
    - Ctrl+Z triggers undo, Ctrl+Shift+Z triggers redo
    - Clear session on navigate away from /db
    - _Requirements: 29.1, 29.2, 29.3, 29.4, 29.5, 29.6, 29.7_

  - [x] 19.3 Write property test for undo reversal (Python/Hypothesis)
    - **Property 15: Undo reversal**
    - Test that for any single operation, undo restores exact pre-operation state
    - **Validates: Requirements 29.1, 29.2, 29.3, 29.4**

- [x] 20. CSV import/export
  - [x] 20.1 Implement CSV export endpoint
    - `GET /api/db/:schema/:table/export-csv` — stream all matching rows as CSV (respects filters/search)
    - Return Content-Type text/csv with Content-Disposition attachment header
    - _Requirements: 30.1_

  - [x] 20.2 Implement CSV import endpoint
    - `POST /api/db/:schema/:table/import-csv` — multipart form (file + mapping JSON)
    - Parse CSV, apply column mapping, cast values, insert row-by-row
    - Continue on constraint violations, collect errors
    - Return { total_rows, imported_rows, failed_rows: [{ line_number, error }] }
    - _Requirements: 30.4, 30.5, 30.6_

  - [x] 20.3 Implement `CsvImportDialog.tsx`
    - File picker for .csv, parse headers + first 5 rows for preview
    - Column mapping UI: each CSV column → table column dropdown or "Skip"
    - Auto-map by name match
    - Import button with progress, results display with success/error counts
    - _Requirements: 30.2, 30.3_

  - [x] 20.4 Write property test for CSV export/import round-trip (Python/Hypothesis)
    - **Property 16: CSV export/import round-trip**
    - Test that exporting and re-importing with identity mapping preserves values
    - **Validates: Requirements 30.1, 30.4**

- [x] 21. Relation views
  - [x] 21.1 Implement relations API endpoint
    - `GET /api/db/:schema/:table/:id/relations` — query information_schema for FK references
    - Return RelationGroup[] with schema, table, fk_column, total_count, and up to 5 rows
    - _Requirements: 31.1, 31.5_

  - [x] 21.2 Implement `RelationSections.tsx` in DetailView
    - Expandable accordion per referencing table
    - Header: related table name + count badge
    - Body: compact mini-table (3-4 key columns, max 5 rows)
    - "View all" link → navigates to related table pre-filtered
    - "Add" button → CreateRowDialog with FK field pre-filled and read-only
    - _Requirements: 31.1, 31.2, 31.3, 31.4_

  - [x] 21.3 Write property test for relation discovery completeness (Python/Hypothesis)
    - **Property 18: Relation discovery completeness**
    - Test that ALL tables with FK columns referencing the target table are returned
    - **Validates: Requirements 31.1, 31.5**

- [x] 22. Checkpoint - Advanced features complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 23. Inbox processing
  - [x] 23.1 Implement inbox API endpoints
    - `GET /api/db/inbox/files` — list inbox directory files
    - `GET /api/db/inbox/tables` — tables with image support
    - `POST /api/db/inbox/process` — create row + link photos
    - `POST /api/db/inbox/ai-extract` — proxy to Smart Capture extract
    - `POST /api/db/inbox/url-extract` — proxy to URL scrape pipeline
    - `POST /api/db/inbox/knowledge` — create knowledge note + move photos
    - _Requirements: 19.1, 19.3, 19.5, 19.6, 19.7, 20.3, 20.4_

  - [x] 23.2 Implement `InboxProcessor.tsx`
    - Thumbnail grid of inbox files with click-to-select (numbered selection)
    - Target table dropdown for tables with image support
    - Form with SmartFieldRenderer for all table columns
    - "AI Fill" button (sends photo through Smart Capture, populates form, highlights AI-filled)
    - "Fill from URL" button (scrapes URL, populates form)
    - Save commits row + links photos + removes from inbox view
    - Knowledge Note mode: topic + title + notes textarea
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7, 20.1, 20.2, 20.3, 20.4, 20.5_

- [x] 24. Theme reactivity and mobile layout
  - [x] 24.1 Apply theme CSS custom properties to all DB Browser components
    - Use only CSS variables from existing BowersHub theme system
    - Ensure legibility across all themes including OLED Black and light themes
    - No hardcoded colors
    - _Requirements: 22.1, 22.2, 22.3_

  - [x] 24.2 Implement responsive mobile layout
    - SchemaSidebar collapses to overlay drawer at < 640px with hamburger toggle
    - TableView enables horizontal scroll and condensed row height on mobile
    - DetailView renders single-column layout on mobile regardless of width settings
    - Touch-friendly hit targets (minimum 44x44px)
    - Swipe gestures for row navigation on touch devices
    - _Requirements: 23.1, 23.2, 23.3, 23.4, 23.5_

- [x] 25. Non-admin read-only mode
  - [x] 25.1 Implement read-only mode for non-admin users
    - Track `isAdmin` from auth context
    - Hide all write controls (Save, Add, Delete, Create Table, etc.) for non-admin users
    - Backend `require_admin` returns 403 as safety net
    - _Requirements: 21.2, 21.3_

- [x] 26. Final checkpoint - Full integration
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design
- Backend uses Python with Hypothesis for property tests; frontend uses TypeScript with fast-check
- The existing `db_admin_field_hints` table is reused (no migration needed for it)
- All frontend components use CSS custom properties from the theme system (NO HARDCODING)
- All configuration is database-driven per project rules

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "1.4"] },
    { "id": 1, "tasks": ["2.1", "2.2", "4.1"] },
    { "id": 2, "tasks": ["2.3", "2.4", "2.5", "4.2", "4.3"] },
    { "id": 3, "tasks": ["2.6", "2.7", "5.1", "5.2"] },
    { "id": 4, "tasks": ["2.8", "2.9", "2.10", "2.11", "5.3", "5.4", "5.5"] },
    { "id": 5, "tasks": ["5.6", "6.1", "6.2", "6.6"] },
    { "id": 6, "tasks": ["6.3", "6.4", "6.5", "8.1"] },
    { "id": 7, "tasks": ["6.7", "6.8", "6.9", "8.2", "9.1"] },
    { "id": 8, "tasks": ["9.2", "9.3", "9.4", "10.1", "10.2"] },
    { "id": 9, "tasks": ["10.3", "11.1", "11.2", "11.3"] },
    { "id": 10, "tasks": ["13.1", "13.2", "16.1"] },
    { "id": 11, "tasks": ["13.3", "14.1", "15.1", "16.2"] },
    { "id": 12, "tasks": ["14.2", "16.3", "16.4", "16.5"] },
    { "id": 13, "tasks": ["16.6", "18.1", "19.1"] },
    { "id": 14, "tasks": ["18.2", "18.3", "19.2"] },
    { "id": 15, "tasks": ["19.3", "20.1", "20.2"] },
    { "id": 16, "tasks": ["20.3", "20.4", "21.1"] },
    { "id": 17, "tasks": ["21.2", "21.3", "23.1"] },
    { "id": 18, "tasks": ["23.2", "24.1", "24.2"] },
    { "id": 19, "tasks": ["25.1"] }
  ]
}
```
