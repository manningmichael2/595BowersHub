# Requirements Document

## Introduction

This feature replaces the standalone Flask-based DB Admin app (port 5002, separate container, vanilla JS) with a native React-based database browser built directly into BowersHub AI (port 5003). The native DB browser provides full feature parity with the existing DB Admin — table browsing, row editing, smart field inputs, image management, filtering, sorting, schema management, inbox processing, and field property configuration — while gaining unified navigation, shared JWT auth, theme reactivity, and mobile-optimized UX. Once complete, the standalone DB Admin container can be retired.

## Glossary

- **DB_Browser**: The React-based database browser feature inside BowersHub AI, accessible via the `/db` route and its child routes.
- **DB_API**: A set of FastAPI endpoints under `/api/db/` that provide schema introspection, CRUD operations, image management, and field hint configuration.
- **Table_View**: The paginated list of rows for a selected table, with sortable columns, filters, and search.
- **Detail_View**: The single-row editing form with smart field inputs, image management, and navigation between rows.
- **Smart_Field_Renderer**: A component system that maps column names and types to appropriate input widgets (dropdowns, fraction inputs, currency fields, date pickers, etc.) based on field hint configuration.
- **Field_Hint**: A per-column configuration record (stored in `db_admin_field_hints` table) that defines input type, dropdown options, prefix/suffix, min/max/step, and placeholder for the Smart_Field_Renderer.
- **Schema_Sidebar**: The left-panel navigation showing all schemas and their tables, with context menu actions for schema management.
- **Layout_Config**: Per-table display preferences (field order, visibility, width, height for detail view; column order and visibility for list view) persisted to the backend.
- **Inbox_Processor**: The workflow for selecting inbox photos, choosing a target table or knowledge mode, optionally running AI extraction, and committing records.
- **Link_Table**: A join table (e.g., `inventory.tool_files`) that connects a domain record to `files.assets` entries, enabling image support for any table.
- **Saved_View**: A named, per-user per-table configuration record storing a combination of filter conditions, sort order, and column visibility, persisted in `bh_db_browser_views`.
- **Undo_Log**: A server-side session-scoped stack of data operations (edits, creates, deletes) with their prior values, enabling reversible data changes within a browser session.

## Requirements

### Requirement 1: Route and Navigation Integration

**User Story:** As Michael, I want the database browser accessible as a route inside BowersHub AI, so that I can manage my data without switching to a separate app or container.

#### Acceptance Criteria

1. THE DB_Browser SHALL render at the `/db` route within the existing React router, with nested routes for table views (`/db/:schema/:table`) and row detail (`/db/:schema/:table/:id`).
2. WHEN the user taps the database icon in the Sidebar, THE DB_Browser SHALL navigate to `/db` without a full page reload.
3. THE DB_Browser SHALL display the Schema_Sidebar on the left (collapsible on mobile) and the main content area on the right.
4. WHEN the user navigates to `/db` without a table selected, THE DB_Browser SHALL display a welcome state showing schema/table counts and quick links to recently viewed tables.
5. THE DB_Browser SHALL support browser back/forward navigation between tables and detail views using standard React Router history entries.

### Requirement 2: Schema and Table Discovery

**User Story:** As Michael, I want to see all schemas and tables in the sidebar, so that I can browse any part of my database.

#### Acceptance Criteria

1. THE DB_API SHALL expose `GET /api/db/schemas` returning all user-accessible schemas with their tables, column counts, and row counts.
2. THE Schema_Sidebar SHALL display schemas as collapsible groups with tables listed alphabetically within each group.
3. THE DB_API SHALL load all schemas in parallel to minimize initial load time.
4. THE Schema_Sidebar SHALL visually distinguish tables that have an associated Link_Table (indicating image support) with an icon indicator.
5. WHEN a table is selected in the Schema_Sidebar, THE DB_Browser SHALL highlight the active table and navigate to the Table_View for that table.

### Requirement 3: Table View with Pagination

**User Story:** As Michael, I want to view rows in a table with pagination, so that I can browse large datasets without loading everything at once.

#### Acceptance Criteria

1. THE DB_API SHALL expose `GET /api/db/:schema/:table/rows` returning paginated rows with configurable page size (default 50), total row count, and column metadata.
2. THE Table_View SHALL display rows in a scrollable table with column headers, supporting horizontal scroll on narrow viewports.
3. THE Table_View SHALL render pagination controls showing current page, total pages, and page size selector (25, 50, 100).
4. WHEN a table has image support via a Link_Table, THE Table_View SHALL display thumbnail previews of the primary image in each row.
5. WHEN the user clicks a row, THE DB_Browser SHALL navigate to the Detail_View for that row.

### Requirement 4: Column Sorting

**User Story:** As Michael, I want to sort table data by clicking column headers, so that I can quickly find records by any field.

#### Acceptance Criteria

1. WHEN the user clicks a column header, THE Table_View SHALL sort rows by that column in ascending order.
2. WHEN the user clicks the same column header again, THE Table_View SHALL toggle to descending order.
3. WHEN the user clicks the column header a third time, THE Table_View SHALL clear the sort and return to the default order (primary key descending).
4. THE Table_View SHALL display a sort direction indicator (arrow icon) on the currently sorted column.
5. THE DB_API SHALL perform sorting server-side so that sort applies across all pages, not just the visible page.

### Requirement 5: Filtering

**User Story:** As Michael, I want to filter rows by column values using various conditions, so that I can narrow down to the records I need.

#### Acceptance Criteria

1. THE Table_View SHALL provide a filter builder UI that allows adding one or more filter conditions.
2. THE Table_View SHALL support the following filter operators: equals, not equals, contains, greater than, less than, is null, and has value (is not null).
3. WHEN multiple filters are active, THE DB_API SHALL combine them with AND logic.
4. THE Table_View SHALL display active filter count as a badge on the filter button.
5. WHEN filters are active, THE DB_API SHALL apply them server-side and return the filtered row count alongside the total row count.

### Requirement 6: Text Search

**User Story:** As Michael, I want to search across all text columns in a table, so that I can find records by any visible text without knowing which column contains it.

#### Acceptance Criteria

1. THE Table_View SHALL provide a search input that accepts free text.
2. WHEN the user types a search term, THE DB_API SHALL search across all text-type columns (text, varchar, character varying) in the table using case-insensitive partial matching.
3. THE DB_API SHALL debounce search requests by 300 milliseconds to avoid excessive queries while the user types.
4. WHEN a search term is active, THE Table_View SHALL indicate the matched row count.
5. THE Table_View SHALL allow combining search with column filters simultaneously.

### Requirement 7: Row Detail View and Editing

**User Story:** As Michael, I want to open a row and edit its fields using appropriate input widgets, so that I can update data accurately with a good UX.

#### Acceptance Criteria

1. THE Detail_View SHALL display all editable columns for a row in a form layout, using the Smart_Field_Renderer for each column.
2. WHEN the user modifies a field and clicks Save, THE DB_API SHALL update the row via `PATCH /api/db/:schema/:table/:id` and return the updated row.
3. IF a save operation fails due to a constraint violation, THEN THE DB_API SHALL return a human-readable error message identifying the violated constraint.
4. THE Detail_View SHALL display read-only fields (primary key, created_at, updated_at) with a visual distinction from editable fields.
5. THE Detail_View SHALL provide navigation buttons to move to the previous or next row in the current table view (respecting active filters and sort order).

### Requirement 8: Smart Field Rendering

**User Story:** As Michael, I want columns to automatically render as the right input type (dropdowns, fractions, currencies, toggles, date pickers), so that data entry is fast and accurate.

#### Acceptance Criteria

1. THE Smart_Field_Renderer SHALL read Field_Hint configuration from the DB_API to determine the input type, prefix, suffix, dropdown options, and validation rules for each column.
2. WHEN a column named `condition` is rendered, THE Smart_Field_Renderer SHALL display a dropdown with options: new, excellent, good, fair, worn, damaged, broken.
3. WHEN a column name ends with `_in` (measurement fields), THE Smart_Field_Renderer SHALL display a fraction input that shows values like "3/8\"" while storing the decimal equivalent, and SHALL accept either fraction or decimal input.
4. WHEN a column named `purchase_price` or `current_value_estimate` is rendered, THE Smart_Field_Renderer SHALL display a number input with a "$" prefix.
5. WHEN a column named `angle_deg` is rendered, THE Smart_Field_Renderer SHALL display a number input with range 0-360 and a "°" suffix.
6. WHEN a boolean column is rendered, THE Smart_Field_Renderer SHALL display a Yes/No toggle.
7. WHEN a column named `url` is rendered, THE Smart_Field_Renderer SHALL display a URL input with a clickable link icon to open the URL in a new tab.
8. WHEN a date-type column is rendered, THE Smart_Field_Renderer SHALL display a native date picker.
9. WHEN a column named `notes` is rendered, THE Smart_Field_Renderer SHALL display a resizable textarea.
10. WHEN a column name ends with `_id` and has a foreign key relationship, THE Smart_Field_Renderer SHALL display a lookup dropdown populated from the referenced table with a hyperlink to navigate to the linked record.

### Requirement 9: Image Management

**User Story:** As Michael, I want to upload, view, reorder, and manage photos attached to records, so that I can visually document my inventory items.

#### Acceptance Criteria

1. WHEN a table has an associated Link_Table, THE Detail_View SHALL display an image gallery section showing all linked photos as thumbnails.
2. THE Detail_View SHALL allow uploading new images via file picker or drag-and-drop, with the upload processed through the existing file upload infrastructure and linked via the Link_Table.
3. THE Detail_View SHALL allow reordering images via drag-and-drop to change display priority.
4. THE Detail_View SHALL allow setting a primary image (indicated by a star icon), which is the image shown in the Table_View thumbnail.
5. THE Detail_View SHALL allow unlinking an image from a record (removing the Link_Table row without deleting the file from disk).
6. WHEN an image thumbnail is tapped, THE DB_Browser SHALL display a full-size preview overlay.

### Requirement 10: Layout Customization — Detail View

**User Story:** As Michael, I want to configure field order, visibility, and width per table in the detail view, so that important fields are at the top and rarely-used fields are hidden.

#### Acceptance Criteria

1. THE Detail_View SHALL provide a layout settings panel (toggled via a gear icon) where the user can reorder fields via drag-and-drop.
2. THE Detail_View SHALL allow hiding fields from the form without deleting data.
3. THE Detail_View SHALL allow setting field width (25%, 33%, 50%, or 100% of the form width) to control multi-column layout.
4. THE Detail_View SHALL allow setting field height (small, medium, large) for textarea and similar tall inputs.
5. THE DB_API SHALL expose `GET /api/db/layouts/:schema/:table` and `PUT /api/db/layouts/:schema/:table` for persisting per-table layout configuration.
6. IF no saved layout exists for a table, THEN THE Detail_View SHALL render all columns in database column order at 50% width.

### Requirement 11: List View Column Customization

**User Story:** As Michael, I want to show, hide, and reorder columns in the table list view, so that I only see the fields that matter for browsing.

#### Acceptance Criteria

1. THE Table_View SHALL provide a column settings panel (toggled via a gear icon) where the user can toggle visibility and reorder columns.
2. THE Table_View SHALL persist column visibility and order preferences in the same layout configuration as the detail view.
3. IF no column preferences are saved, THEN THE Table_View SHALL show all columns except those wider than typical (notes, full URLs) and order them by database column order.
4. THE Table_View SHALL always show the primary key column regardless of visibility settings.

### Requirement 12: Create and Add Rows

**User Story:** As Michael, I want to add new rows to any table using the same smart field rendering, so that data entry for new records is consistent with editing.

#### Acceptance Criteria

1. THE Table_View SHALL provide an "Add Row" button that opens a creation form.
2. THE creation form SHALL use the same Smart_Field_Renderer as the Detail_View, with fields pre-populated with column defaults where defined.
3. WHEN the user submits the creation form, THE DB_API SHALL insert the row via `POST /api/db/:schema/:table` and return the new row with its generated primary key.
4. IF the insert fails due to a constraint violation, THEN THE DB_API SHALL return a human-readable error message.
5. WHEN a row is successfully created, THE DB_Browser SHALL navigate to the Detail_View for the new row.

### Requirement 13: Duplicate Row

**User Story:** As Michael, I want to duplicate an existing row to quickly create similar records, so that I don't have to re-enter shared fields manually.

#### Acceptance Criteria

1. THE Detail_View SHALL provide a "Duplicate" button that creates a new row pre-filled with all field values from the current row except the primary key and timestamp columns.
2. WHEN the user clicks Duplicate, THE DB_Browser SHALL open the creation form with pre-filled values, allowing the user to modify fields before saving.
3. WHEN the duplicated row is saved, THE DB_API SHALL insert it as a new record with a new primary key.

### Requirement 14: Schema Management — Create Table

**User Story:** As Michael, I want to create new tables with a visual column builder, so that I can extend my database without writing raw SQL.

#### Acceptance Criteria

1. THE Schema_Sidebar SHALL provide a "New Table" action accessible via a button or context menu.
2. THE DB_Browser SHALL display a table creation form with: schema selector, table name input, and a dynamic column builder.
3. THE column builder SHALL support adding columns with name, data type (text, integer, decimal, boolean, date, timestamp, lookup), nullable toggle, and default value.
4. THE DB_Browser SHALL display a live SQL preview of the CREATE TABLE statement as the user builds the table definition.
5. WHEN the user selects "Include image support", THE DB_API SHALL automatically create the corresponding Link_Table (e.g., `schema.tablename_files`) alongside the main table.
6. WHEN the user submits the table creation, THE DB_API SHALL execute the DDL via `POST /api/db/tables` and refresh the Schema_Sidebar to show the new table.

### Requirement 15: Schema Management — Create Schema

**User Story:** As Michael, I want to create new schemas to organize related tables, so that my database stays structured as it grows.

#### Acceptance Criteria

1. THE Schema_Sidebar SHALL provide a "New Schema" action.
2. WHEN the user submits a schema name, THE DB_API SHALL execute `CREATE SCHEMA` via `POST /api/db/schemas` and refresh the Schema_Sidebar.
3. IF the schema name conflicts with an existing schema, THEN THE DB_API SHALL return an error message without executing the DDL.

### Requirement 16: Schema Management — Table Operations

**User Story:** As Michael, I want to rename tables, move them between schemas, and add or delete columns, so that I can evolve my database structure without raw SQL.

#### Acceptance Criteria

1. THE Schema_Sidebar SHALL provide a context menu on each table with actions: Rename, Move to Schema, Add Column, and Delete Column.
2. WHEN the user renames a table, THE DB_API SHALL execute `ALTER TABLE ... RENAME TO` via `PATCH /api/db/tables/:schema/:table`.
3. WHEN the user moves a table to a different schema, THE DB_API SHALL execute `ALTER TABLE ... SET SCHEMA` via `PATCH /api/db/tables/:schema/:table`.
4. WHEN the user adds a column, THE DB_Browser SHALL display a form for column name, data type, nullable, and default value, then THE DB_API SHALL execute `ALTER TABLE ... ADD COLUMN`.
5. WHEN the user deletes a column, THE DB_Browser SHALL display a dropdown of existing columns (excluding primary key) and require confirmation before THE DB_API executes `ALTER TABLE ... DROP COLUMN`.

### Requirement 17: Lookup Columns (Foreign Key Dropdowns)

**User Story:** As Michael, I want foreign key columns rendered as dropdowns with human-readable labels and hyperlinks to the linked record, so that I can navigate relationships easily.

#### Acceptance Criteria

1. WHEN a column has a foreign key constraint, THE Smart_Field_Renderer SHALL display a dropdown populated with rows from the referenced table.
2. THE dropdown SHALL display a human-readable label derived from the referenced table's display columns (first text column, or `name`/`title`/`description` if present).
3. THE Smart_Field_Renderer SHALL display a hyperlink icon next to the dropdown that navigates to the Detail_View of the linked record when clicked.
4. THE DB_API SHALL expose `GET /api/db/:schema/:table/lookup-options/:column` returning the list of available options with id and display label.
5. WHEN the referenced table has more than 200 rows, THE lookup dropdown SHALL support type-ahead search rather than loading all options at once.

### Requirement 18: Field Properties Settings

**User Story:** As Michael, I want to configure input types, dropdown options, and prefix/suffix for any column through a settings UI, so that the smart field system adapts to new columns without code changes.

#### Acceptance Criteria

1. THE DB_Browser SHALL provide a "Field Settings" page accessible from the sidebar or a settings icon.
2. THE Field Settings page SHALL list all columns across all user schemas, showing column name, which tables the column appears in, and the current Field_Hint configuration.
3. THE Field Settings page SHALL allow setting: input type (text, number, fraction, select, url, date, boolean, textarea), prefix text, suffix text, min/max/step for numbers, placeholder text, and dropdown option list.
4. THE DB_API SHALL expose `GET /api/db/field-hints` and `PUT /api/db/field-hints/:column_name` for reading and saving Field_Hint records.
5. WHEN a Field_Hint is saved, THE Smart_Field_Renderer SHALL use the updated configuration immediately on next render without requiring a page reload.
6. THE Field Settings page SHALL support filtering columns by "All", "Configured", and "Unconfigured" states, and searching by column name.

### Requirement 19: Inbox Processing — Inventory Records

**User Story:** As Michael, I want to select photos from my inbox, pick a target table, optionally run AI extraction to pre-fill fields, and commit the record, so that I can quickly catalog items from photos.

#### Acceptance Criteria

1. THE DB_Browser SHALL provide an "Inbox" page accessible from the sidebar, displaying thumbnails of all files in the inbox directory.
2. THE Inbox_Processor SHALL allow selecting one or more photos by tapping thumbnails (showing selection order numbers).
3. THE Inbox_Processor SHALL allow choosing a target table from a dropdown of all tables with image support.
4. WHEN a target table is selected, THE Inbox_Processor SHALL display a creation form with all table columns rendered via the Smart_Field_Renderer.
5. THE Inbox_Processor SHALL provide an "AI Fill" button that sends the first selected photo through the Smart Capture extract pipeline and populates the form fields with the extracted values (highlighted to indicate AI-filled content).
6. THE Inbox_Processor SHALL provide a "Fill from URL" button that accepts a product URL, scrapes it via the existing extract pipeline, and populates the form fields.
7. WHEN the user submits the inbox form, THE DB_API SHALL create the row in the target table, link the selected photos via the Link_Table, and remove the processed files from the inbox view.

### Requirement 20: Inbox Processing — Knowledge Capture

**User Story:** As Michael, I want to create markdown knowledge notes from inbox photos, so that I can capture information that doesn't fit a database table.

#### Acceptance Criteria

1. THE Inbox_Processor SHALL provide a "Knowledge Note" mode toggle as an alternative to table record mode.
2. WHEN in knowledge mode, THE Inbox_Processor SHALL display a form with topic input, title input, and a notes textarea.
3. WHEN the user submits a knowledge note, THE DB_API SHALL create a markdown file at `/knowledge/<topic>/<slug>.md` with the note content and embedded photo references.
4. WHEN a knowledge note is submitted, THE DB_API SHALL move the selected photos to `/files/knowledge/<slug>/` and register them in `files.assets`.
5. AFTER a successful knowledge note submission, THE Inbox_Processor SHALL remove the processed files from the inbox view.

### Requirement 21: Authentication and Authorization

**User Story:** As Michael, I want the DB browser to require authentication and be restricted to admin users, so that my database is protected behind proper access control.

#### Acceptance Criteria

1. THE DB_API SHALL require a valid JWT token on all endpoints, using the existing BowersHub AI authentication middleware.
2. THE DB_API SHALL restrict all write operations (insert, update, delete, DDL) to users with the admin role.
3. IF a non-admin user accesses the DB_Browser, THEN THE DB_Browser SHALL display a read-only view with editing controls disabled.
4. IF an unauthenticated request is made to a DB_API endpoint, THEN THE DB_API SHALL return HTTP 401.

### Requirement 22: Theme Reactivity

**User Story:** As Michael, I want the database browser to follow my theme choice, so that it looks native within BowersHub AI regardless of theme.

#### Acceptance Criteria

1. THE DB_Browser SHALL use only CSS custom properties from the existing BowersHub theme system for all UI chrome (backgrounds, borders, text, accents).
2. WHEN the user changes their theme in Settings, THE DB_Browser SHALL re-render with updated colors without a page reload.
3. THE DB_Browser SHALL render legibly across all existing preset themes including OLED Black and light-background themes.

### Requirement 23: Mobile-Friendly Layout

**User Story:** As Michael, I want the database browser to work well on my phone, so that I can view and edit records from anywhere.

#### Acceptance Criteria

1. WHILE the viewport width is less than 640px, THE Schema_Sidebar SHALL collapse to an overlay drawer toggled by a hamburger menu button.
2. WHILE the viewport width is less than 640px, THE Table_View SHALL enable horizontal scrolling for wide tables and use a condensed row height.
3. WHILE the viewport width is less than 640px, THE Detail_View SHALL render all fields in a single-column layout regardless of width settings.
4. THE DB_Browser SHALL use touch-friendly hit targets (minimum 44x44px) for all interactive elements.
5. THE Detail_View SHALL support swipe gestures for navigating between rows on touch devices.

### Requirement 24: Database-Driven Configuration

**User Story:** As Michael, I want all DB browser configuration stored in the database (not hardcoded), so that adding field hints or layout preferences is a data change not a code change.

#### Acceptance Criteria

1. THE DB_API SHALL read Smart_Field_Renderer configuration from the `db_admin_field_hints` table, with no hardcoded field-to-widget mappings in frontend code.
2. THE DB_API SHALL read layout preferences from a `bh_db_browser_layouts` table, not from localStorage.
3. WHEN a column has no Field_Hint record and no foreign key constraint, THE Smart_Field_Renderer SHALL fall back to a default text input based on the column's Postgres data type (text → text input, numeric → number input, boolean → toggle, date → date picker).
4. THE DB_Browser SHALL not require code changes to support new tables, columns, or schemas added to the database.

### Requirement 25: Inline Cell Editing

**User Story:** As Michael, I want to click any cell in the table view and edit it in place, so that I can quickly update data without navigating away from the list.

#### Acceptance Criteria

1. WHEN the user clicks a cell in the Table_View, THE Smart_Field_Renderer SHALL render in compact (inline) mode within that cell, replacing the static display value with an editable input.
2. WHEN the user presses Tab while editing a cell, THE Table_View SHALL save the current cell value and move focus to the next editable cell in the row.
3. WHEN the user presses Enter while editing a cell, THE Table_View SHALL save the current cell value and move focus to the cell directly below in the same column.
4. WHEN the user presses Escape while editing a cell, THE Table_View SHALL discard unsaved changes and return the cell to its static display state.
5. WHEN a cell loses focus (blur) while in edit mode, THE DB_API SHALL persist the changed value immediately via `PATCH /api/db/:schema/:table/:id`.
6. IF a cell save operation fails due to a constraint violation, THEN THE Table_View SHALL revert the cell to its previous value and display the error message as a toast notification.

### Requirement 26: Keyboard Navigation

**User Story:** As Michael, I want full keyboard navigation in the table view, so that I can browse and edit data quickly without touching the mouse.

#### Acceptance Criteria

1. WHEN the user presses an arrow key while a cell is focused (not in edit mode), THE Table_View SHALL move the focus indicator to the adjacent cell in the corresponding direction.
2. WHEN the user presses Tab or Shift+Tab while a cell is focused, THE Table_View SHALL move focus to the next or previous editable cell respectively, wrapping to the next or previous row at row boundaries.
3. WHEN the user presses Enter on a focused cell that is not in edit mode, THE Table_View SHALL activate inline editing for that cell.
4. WHEN the user presses Ctrl+N while the Table_View is active, THE DB_Browser SHALL open the Create Row form.
5. WHEN the user presses Ctrl+D while a row is selected, THE DB_Browser SHALL duplicate the selected row using the same logic as the Duplicate button in the Detail_View.
6. WHEN the user presses Ctrl+F while the Table_View is active, THE Table_View SHALL move focus to the search input field.
7. WHEN the user presses Delete while a row is selected (not in cell edit mode), THE DB_Browser SHALL display a deletion confirmation dialog for the selected row.

### Requirement 27: Bulk Operations

**User Story:** As Michael, I want to select multiple rows and perform actions on them at once, so that I can efficiently manage large datasets without repetitive one-by-one operations.

#### Acceptance Criteria

1. THE Table_View SHALL display a checkbox column as the first column, allowing the user to select individual rows or select all visible rows via a header checkbox.
2. WHEN the user holds Shift and clicks a row checkbox, THE Table_View SHALL select all rows between the last selected row and the clicked row (range selection).
3. WHEN one or more rows are selected, THE Table_View SHALL display a bulk actions toolbar showing the count of selected rows and action buttons for Delete, Edit Field, and Export CSV.
4. WHEN the user triggers bulk delete, THE DB_Browser SHALL display a confirmation dialog showing the exact count of rows to be deleted, and upon confirmation THE DB_API SHALL delete all selected rows.
5. WHEN the user triggers bulk edit, THE DB_Browser SHALL display a dialog allowing the user to pick a single column, set a value using the Smart_Field_Renderer, and apply that value to all selected rows.
6. WHEN the user triggers bulk export, THE DB_Browser SHALL generate and download a CSV file containing only the selected rows with all visible columns.

### Requirement 28: Saved Views (Named Filters)

**User Story:** As Michael, I want to save combinations of filters, sort, and column visibility as named views, so that I can quickly switch between different ways of looking at the same table.

#### Acceptance Criteria

1. THE Table_View SHALL display a tab bar above the table showing all saved views for the current table, with a default "All" view that applies no filters or custom sort.
2. WHEN the user clicks "Save View" with active filters, sort, or column visibility settings, THE DB_Browser SHALL prompt for a view name and persist the configuration via the DB_API.
3. WHEN the user selects a saved view tab, THE Table_View SHALL apply the stored filters, sort order, and column visibility settings immediately.
4. THE DB_API SHALL expose `GET /api/db/views/:schema/:table` and `POST /api/db/views/:schema/:table` for reading and creating per-user per-table view configurations.
5. THE DB_Browser SHALL allow renaming and deleting saved views via a context menu on the view tab, with the "All" view being undeletable.
6. THE DB_API SHALL store saved views in the `bh_db_browser_views` table, scoped per user and per table, including filter conditions, sort column, sort direction, and column visibility as a JSONB payload.

### Requirement 29: Undo/Redo

**User Story:** As Michael, I want to undo and redo my recent data changes, so that I can recover from mistakes without manually reverting values.

#### Acceptance Criteria

1. WHEN the user presses Ctrl+Z after editing a cell value, THE DB_Browser SHALL revert the field to its previous value by issuing a PATCH request with the stored prior value.
2. WHEN the user presses Ctrl+Z after creating a row, THE DB_Browser SHALL delete the newly created row via the DB_API.
3. WHEN the user presses Ctrl+Z after deleting a row, THE DB_Browser SHALL restore the deleted row by re-inserting it with all original field values via the DB_API.
4. WHEN the user presses Ctrl+Z after a bulk edit operation, THE DB_Browser SHALL revert all affected rows to their prior values as a single undo operation.
5. WHEN the user presses Ctrl+Shift+Z, THE DB_Browser SHALL re-apply the most recently undone operation.
6. THE DB_Browser SHALL store previous values server-side (in a session-scoped undo log) so that undone changes persist correctly across page refreshes within the same session.
7. WHEN the user navigates away from the DB_Browser route, THE DB_Browser SHALL clear the undo/redo stack for the session.

### Requirement 30: CSV Import/Export

**User Story:** As Michael, I want to import and export CSV files, so that I can move data between my database and spreadsheets or other tools.

#### Acceptance Criteria

1. WHEN the user clicks "Export CSV" on the Table_View, THE DB_Browser SHALL generate and download a CSV file containing all rows matching the current filters and search term, with column headers.
2. WHEN the user clicks "Import CSV" on the Table_View, THE DB_Browser SHALL display a file picker that accepts `.csv` files and a column mapping interface.
3. WHEN a CSV file is uploaded, THE DB_Browser SHALL display a preview of the first 5 rows with a mapping UI that lets the user assign each CSV column to a table column or skip it.
4. WHEN the user confirms the import, THE DB_API SHALL insert the mapped rows into the table and return a result summary including the count of successfully imported rows and any failed rows with error descriptions.
5. IF one or more rows fail during import due to constraint violations or type mismatches, THEN THE DB_API SHALL continue importing valid rows and return a detailed error list identifying each failed row by its CSV line number and the specific error.
6. THE DB_API SHALL expose `POST /api/db/:schema/:table/import-csv` accepting multipart form data with the CSV file and a column mapping JSON payload.

### Requirement 31: Relation Views

**User Story:** As Michael, I want to see related records from other tables when viewing a record, so that I can understand relationships and navigate between linked data without manual queries.

#### Acceptance Criteria

1. WHEN the Detail_View is displayed for a row, THE DB_Browser SHALL query the database for all tables that have foreign key columns referencing the current table and display matching related records in expandable sections below the main form.
2. THE Detail_View SHALL display each relation section with the related table name as a header, showing the 5 most recently created related records in a compact mini table format.
3. WHEN a relation section contains more than 5 related records, THE Detail_View SHALL display a "View all" link that navigates to the related table's Table_View pre-filtered to show only records linked to the current row.
4. THE Detail_View SHALL provide an "Add" button in each relation section that opens a Create Row form for the related table, pre-filling the foreign key field with the current row's primary key value.
5. THE DB_API SHALL expose `GET /api/db/:schema/:table/:id/relations` returning all related records grouped by referencing table, limited to 5 rows per relation with a total count for each.
