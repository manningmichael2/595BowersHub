# Implementation Plan: Financial AI Advisor

## Overview

This plan migrates the existing SimpleFin → n8n → JSON → AnythingLLM pipeline to a PostgreSQL-backed architecture with AI categorization, transfer detection, house tagging, budget alerts, and a webhook-first chat interface. All n8n workflow changes are done via the n8n UI or API. The init SQL script and test files live on the host filesystem. Tasks are ordered: infrastructure → data layer → processing → query → alerting → AI → migration → testing.

## Tasks

- [x] 1. Deploy PostgreSQL infrastructure
  - [x] 1.1 Create the init SQL script on the host filesystem
    - Write the full DDL to `/home/michael/finance/init/01_init.sql`
    - Include all tables: `accounts`, `transactions`, `categories`, `budgets`, `alert_log`
    - Include all indexes, triggers, and the `update_updated_at()` function
    - Pre-seed the 17 system categories with `ON CONFLICT DO NOTHING`
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 4.4_

  - [x] 1.2 Create the `init` directory and `postgres-data` directory on the host
    - Ensure `/home/michael/finance/init/` exists (for the SQL script mount)
    - Ensure `/home/michael/finance/postgres-data/` exists (for the data volume)
    - _Requirements: 1.6, 1.7_

  - [x] 1.3 Add the Postgres service to the Docker stack via Portainer
    - Use `postgres:16-alpine` image
    - Set container name and hostname to `postgres`
    - Configure environment: `POSTGRES_DB=finance`, `POSTGRES_USER=finance_user`, `POSTGRES_PASSWORD` from Portainer env var
    - Mount volumes: `/home/michael/finance/postgres-data:/var/lib/postgresql/data` and `/home/michael/finance/init:/docker-entrypoint-initdb.d:ro`
    - Join the existing `ai-network` Docker network
    - Add healthcheck: `pg_isready -U finance_user -d finance`
    - Do NOT expose port 5432 to the host
    - _Requirements: 1.1, 1.6, 1.7, 1.8_

- [x] 2. Checkpoint — Verify Postgres is running
  - Ensure the Postgres container starts, the healthcheck passes, and all 5 tables exist with correct columns. Verify the 17 system categories are seeded. Ask the user if questions arise.

- [x] 3. Configure n8n Postgres credential and upsert workflows
  - [x] 3.1 Create the `Finance Postgres` credential in n8n
    - In the n8n UI: Settings → Credentials → Add Credential → Postgres
    - Host: `postgres`, Port: `5432`, Database: `finance`, User: `finance_user`, Password: (from Portainer env var), SSL: disabled
    - Test the connection from n8n to confirm Docker network connectivity
    - _Requirements: 1.8_

  - [x] 3.2 Upgrade the Historical Load workflow to upsert accounts and transactions to Postgres
    - After the SimpleFin HTTP Request node, add a Code node to transform account data into upsert format
    - Add a Postgres node using the `Finance Postgres` credential with Execute Query mode
    - Use the accounts upsert SQL: `INSERT INTO accounts (...) VALUES (...) ON CONFLICT (id) DO UPDATE SET ...`
    - Add a second Code node to transform transaction data into upsert format
    - Add a Postgres node for the transactions upsert SQL (preserving manual override fields — do NOT include `category_id`, `house_tag`, `is_transfer` in the `DO UPDATE SET` clause)
    - Add a workflow variable `DUAL_WRITE` set to `true`
    - Keep the existing Filewriter HTTP call (conditional on `DUAL_WRITE=true`)
    - _Requirements: 2.1, 2.2, 2.5, 2.7, 10.1, 10.4_

  - [x] 3.3 Upgrade the Nightly Sync workflow to upsert accounts and transactions to Postgres
    - Same pattern as Historical Load: Code node → Postgres upsert for accounts, Code node → Postgres upsert for transactions
    - Wrap the Filewriter call in an IF node checking `DUAL_WRITE=true`
    - Add error handling: wrap the Postgres upsert in a try/catch (Error Trigger node) that logs the error and continues processing remaining accounts
    - Add a workflow variable `DUAL_WRITE` set to `true`
    - _Requirements: 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 10.1, 10.4, 10.5_

- [ ] 4. Checkpoint — Verify upsert workflows
  - Run the Historical Load workflow manually. Verify accounts and transactions appear in Postgres with correct data. Re-run it and verify no duplicate rows are created. Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement processing layer — House Tagger
  - [x] 5.1 Add the House Tagger Code node to the Nightly Sync workflow
    - Add a workflow variable `HOUSE_KEYWORDS` as a JSON array: `["595 Bowers", "595Bowers", "Bowers", "Home Depot", "Lowes", "Lowe's", "Mortgage", "HOA", "Property Tax", "Pest Control", "Lawn", "Landscaping", "Plumber", "Electrician", "HVAC", "Roto-Rooter", "ServiceMaster"]`
    - Add a Code node after the transaction upsert that reads `HOUSE_KEYWORDS` from workflow variables
    - Logic: for each transaction where `house_tag_manual = false`, check if `description + memo` contains any keyword (case-insensitive); set `house_tag = true` if match found
    - Add a Postgres node after the Code node: `UPDATE transactions SET house_tag = $1 WHERE id = $2 AND house_tag_manual = false`
    - _Requirements: 6.1, 6.2, 6.5_

  - [x] 5.2 Add the House Tagger to the Historical Load workflow
    - Same Code node logic and Postgres update as in Nightly Sync
    - Reuse the `HOUSE_KEYWORDS` workflow variable
    - _Requirements: 6.1, 6.2, 6.5_

- [x] 6. Implement processing layer — Transfer Detector
  - [x] 6.1 Create the Transfer Detector as a sub-workflow in n8n
    - Create a new workflow named "Transfer Detector"
    - Input: list of newly upserted transaction IDs from the current sync run
    - Add a Postgres node to query the new transactions: `SELECT id, account_id, posted_date, amount, description, memo, is_transfer_manual FROM transactions WHERE id = ANY($1)`
    - Add a Code node implementing the matching algorithm:
      - Separate into debits (amount < 0) and credits (amount > 0)
      - For each debit, find credits where: `ABS(credit.amount) == ABS(debit.amount)`, credit posted 0-3 days after debit, different account_id, both `is_transfer_manual = false`
      - If one match: mark both `is_transfer = true`, assign Transfer category
      - If multiple matches: pick closest `posted_date`, mark that pair only
      - If no match but description/memo contains transfer keyword: append `" | POTENTIAL TRANSFER - REVIEW NEEDED"` to memo
    - Store transfer keywords as a workflow variable: `["Zelle", "Venmo", "ACH Transfer", "Wire Transfer", "Internal Transfer", "XFER", "Transfer From", "Transfer To"]`
    - Add a Postgres node for batch update: `UPDATE transactions SET is_transfer = $1, category_id = $2, memo = $3 WHERE id = $4 AND is_transfer_manual = false`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.6_

  - [x] 6.2 Wire the Transfer Detector into the Nightly Sync workflow
    - After the House Tagger step, add an Execute Sub-Workflow node calling "Transfer Detector"
    - Pass the list of newly upserted transaction IDs as input
    - _Requirements: 5.1_

- [ ] 7. Implement processing layer — Categorizer
  - [x] 7.1 Create the Categorizer sub-workflow in n8n
    - Create a new workflow named "Categorizer"
    - Input: list of transaction objects (or IDs) to categorize
    - Add a Code node to filter out transactions where `user_category_override = true`
    - Add a Code node to split remaining transactions into batches of 50
    - Add a Loop node iterating over each batch
    - Inside the loop: HTTP Request node calling Anthropic API with `claude-haiku-4-5` model
      - 30-second timeout configured on the node
      - Prompt instructs Haiku to return JSON array of `{id, category}` from the predefined list
    - Add a Code node to parse the response:
      - Validate each returned category name exists in the categories list
      - Map category names to `category_id` values
      - If API call failed/timed out: assign `Other` to all transactions in the batch
      - If a returned category name is not in the valid list: assign `Other` to that transaction
    - Add a Postgres node: `UPDATE transactions SET category_id = $1 WHERE id = $2 AND user_category_override = false`
    - _Requirements: 4.1, 4.2, 4.3, 4.5, 4.6, 4.8, 4.9_

  - [ ] 7.2 Wire the Categorizer into the Nightly Sync workflow
    - After the Transfer Detector step, add an Execute Sub-Workflow node calling "Categorizer"
    - Pass only transactions where `category_id IS NULL` (new, uncategorized transactions)
    - _Requirements: 4.1_

  - [ ] 7.3 Add `categorize=true` flag support to the Historical Load workflow
    - Add a workflow variable or manual trigger input `categorize` (boolean, default false)
    - When `categorize=true`: after the upsert, query all transactions where `category_id IS NULL`, pass them to the Categorizer sub-workflow
    - _Requirements: 4.7_

- [ ] 8. Checkpoint — Verify processing layer
  - Run the Nightly Sync workflow. Verify that house tags are applied correctly, transfers are detected between accounts, and new transactions are categorized. Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Upgrade webhooks to SQL-backed queries
  - [ ] 9.1 Upgrade the Balance webhook to query Postgres
    - Replace the existing SimpleFin HTTP call with a Postgres node
    - SQL: `SELECT id, org_name, account_name, currency, last_balance, last_balance_date FROM accounts ORDER BY org_name, account_name`
    - Add error handling: if Postgres is unreachable, return HTTP 503 with `{"error": "Database unavailable."}`
    - _Requirements: 3.1, 3.8_

  - [ ] 9.2 Upgrade the Date-Range webhook to query Postgres
    - Replace the existing SimpleFin HTTP call with a Code node for input validation + Postgres node
    - Validation Code node: check `start` and `end` are in `YYYY-MM-DD` format, check `start` is not after `end`; return HTTP 400 with descriptive error if invalid
    - Postgres query: `SELECT t.*, a.account_name, a.org_name, c.name AS category FROM transactions t JOIN accounts a ON ... LEFT JOIN categories c ON ... WHERE t.posted_date BETWEEN $1 AND $2 ORDER BY t.posted_date DESC`
    - Add error handling for Postgres unavailability (HTTP 503)
    - _Requirements: 3.2, 3.4, 3.5, 3.8_

  - [ ] 9.3 Upgrade the Filter webhook to query Postgres with dynamic WHERE clause
    - Replace the existing SimpleFin HTTP call with a Code node for validation + dynamic SQL building + Postgres node
    - Support parameters: `account`, `min_amount`, `max_amount`, `description`, `category`, `house_tag`
    - Validation: check `min_amount` <= `max_amount` if both provided; return HTTP 400 if violated
    - Build dynamic WHERE clause in Code node (parameterized — no SQL injection)
    - Default date range: last 90 days if no `start`/`end` provided
    - Category filter: case-insensitive exact match against `categories.name`
    - Add error handling for Postgres unavailability (HTTP 503)
    - _Requirements: 3.3, 3.4, 3.6, 3.7, 3.8, 6.3_

- [ ] 10. Checkpoint — Verify webhooks
  - Test each webhook endpoint manually: `/webhook/balances`, `/webhook/transactions?start=...&end=...`, `/webhook/filter?category=Groceries`. Verify correct data is returned and error cases return proper HTTP status codes. Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Implement Budget Alert workflow
  - [ ] 11.1 Create the Budget Alert workflow in n8n
    - Create a new workflow named "Budget Alert"
    - Add a Schedule Trigger node: daily at 8am, timezone America/New_York
    - Add a Postgres node: query current month spending by category (excluding transfers, expenses only)
    - Add a Postgres node: query budget limits for current month from `budgets` table
    - Add a Code node: join spending vs limits, calculate `percentage_used = ROUND(amount_spent / limit_amount * 100)`
    - Add a Code node: filter to categories at ≥80%
    - Add a Postgres node: query `alert_log` for today's already-sent alerts
    - Add a Code node: remove already-alerted categories (dedup)
    - Add an IF node: check if any alerts remain
    - Add a Loop node for remaining alerts:
      - HTTP Request node: POST to `BUDGET_ALERT_WEBHOOK_URL` (n8n environment variable) with JSON body containing `category`, `amount_spent`, `budget_limit`, `percentage_used`, `message`, `title`
      - Postgres node: INSERT into `alert_log` (category_id, alert_type, alert_date, amount_spent, percentage_used)
    - Differentiate alert_type: `80pct` for 80-99%, `100pct` for ≥100%
    - Skip categories with no budget entry (no error, no notification)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

  - [ ] 11.2 Set the `BUDGET_ALERT_WEBHOOK_URL` environment variable in n8n
    - In n8n Settings → Environment Variables, add `BUDGET_ALERT_WEBHOOK_URL` with the target notification endpoint (ntfy.sh topic URL, Slack webhook, or Discord webhook)
    - _Requirements: 7.5_

- [ ] 12. Implement AI layer — Finance Workspace system prompt
  - [ ] 12.1 Update the AnythingLLM Finance Workspace system prompt
    - Navigate to AnythingLLM → Finance Workspace → Settings → System Prompt
    - Write the new webhook-first system prompt that instructs the AI to:
      - ALWAYS call webhooks before answering financial questions
      - Use `/webhook/balances` for balance queries
      - Use `/webhook/transactions?start=...&end=...` for queries spanning >90 days
      - Use `/webhook/filter?...` for category, keyword, house, and single-account queries
      - Exclude transfers from spending/expense/budget queries (handled by SQL)
      - Use `house_tag=true` filter for house/home/property queries
      - Report which endpoint failed if a webhook returns an error
    - Include 3-tier model routing documentation in the prompt:
      - **Opus**: Complex multi-account analysis, financial planning, year-over-year comparisons (use sparingly for cost)
      - **Sonnet**: Standard spending queries, category breakdowns, monthly comparisons (default workspace model)
      - **Haiku**: Simple single-value lookups (balance checks, single category totals)
    - For initial implementation, Sonnet remains the default workspace model
    - Include response format instructions: date range used, total amount, transaction count, top 5 by amount
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 6.4_

- [ ] 13. Implement Auto-Embedding of daily sync files
  - [ ] 13.1 Add the auto-embedding step to the Nightly Sync workflow
    - After the Filewriter step (when `DUAL_WRITE=true`), add an HTTP Request node:
      - POST to `http://anythingllm:3001/api/v1/document/upload` with the daily JSON file as multipart form data
      - Authorization: Bearer token from n8n environment variable `ANYTHINGLLM_API_KEY`
    - Add a second HTTP Request node to embed the uploaded document:
      - POST to `http://anythingllm:3001/api/v1/workspace/finance/update-embeddings` with `{"adds": ["custom-documents/<filename>"], "deletes": []}`
    - Add error handling with retry:
      - IF upload/embed fails → Wait 60 seconds → Retry once
      - IF retry also fails → Log failure (filename, attempt=2, timestamp) and continue (do not fail the workflow)
    - On success: log entry with filename and success indication
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [ ] 13.2 Set the `ANYTHINGLLM_API_KEY` environment variable in n8n
    - In n8n Settings → Environment Variables, add `ANYTHINGLLM_API_KEY` with the API key from AnythingLLM settings
    - _Requirements: 9.1_

- [ ] 14. Checkpoint — Verify AI layer and embedding
  - Test the Finance Workspace by asking a spending question — verify it calls the webhook and returns live data. Trigger a nightly sync and verify the JSON file is auto-embedded. Ensure all tests pass, ask the user if questions arise.

- [ ] 15. Dual-write validation and migration preparation
  - [ ] 15.1 Add validation logic to compare Postgres data against JSON files
    - In the Nightly Sync workflow, after both the Postgres upsert and Filewriter steps, add a Code node that:
      - Counts transactions written to Postgres for this sync
      - Counts transactions in the JSON file written by Filewriter
      - Logs a comparison: `"Postgres: X transactions, JSON: Y transactions, Match: true/false"`
    - This runs only when `DUAL_WRITE=true`
    - _Requirements: 2.6, 10.2, 10.3_

  - [ ] 15.2 Document the cutover procedure
    - Create a file at `/home/michael/finance/MIGRATION_RUNBOOK.md` documenting:
      - Phase 1 (current): `DUAL_WRITE=true`, validate Postgres matches JSON
      - Phase 2: Update system prompt to webhook-first (already done in task 12.1), keep JSON as safety net
      - Phase 3: Set `DUAL_WRITE=false` in both workflows, JSON files stop being written
      - Rollback: Set `DUAL_WRITE=true`, revert system prompt, re-embed JSON files
    - _Requirements: 2.6_

- [ ] 16. Checkpoint — Validate migration readiness
  - Run the Historical Load workflow, then run the Nightly Sync. Verify the validation Code node logs matching counts between Postgres and JSON. Confirm all webhooks return correct data. Ensure all tests pass, ask the user if questions arise.

- [ ] 17. Property-based tests with fast-check
  - [ ] 17.1 Set up the test project structure
    - Create directory `/home/michael/finance/tests/`
    - Initialize a Node.js project: `package.json` with `fast-check` and `vitest` as dependencies
    - Create a `vitest.config.js` with default settings
    - _Requirements: 10.1_

  - [ ]* 17.2 Write property test: Upsert Idempotency (Property 1)
    - **Property 1: Upsert Idempotency**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 10.1, 10.2, 10.3, 10.5**
    - File: `/home/michael/finance/tests/upsert-idempotency.test.js`
    - Generator: arbitrary accounts and transactions with valid SimpleFin IDs
    - Assertion: upserting the same data twice produces identical row count and field values

  - [ ]* 17.3 Write property test: Manual Override Preservation (Property 2)
    - **Property 2: Manual Override Preservation**
    - **Validates: Requirements 2.5, 2.7, 4.6, 6.5, 10.4**
    - File: `/home/michael/finance/tests/manual-override.test.js`
    - Generator: transactions with random combinations of override flags
    - Assertion: protected fields remain unchanged after upsert with different incoming values

  - [ ]* 17.4 Write property test: Categorizer Always Returns Valid Category (Property 3)
    - **Property 3: Categorizer Always Returns Valid Category**
    - **Validates: Requirements 4.2, 4.9**
    - File: `/home/michael/finance/tests/categorizer-valid-category.test.js`
    - Generator: arbitrary strings for description/memo, arbitrary numbers for amount
    - Assertion: result category is always in the predefined VALID_CATEGORIES list

  - [ ]* 17.5 Write property test: Categorizer Batch Size Invariant (Property 4)
    - **Property 4: Categorizer Batch Size Invariant**
    - **Validates: Requirements 4.5, 4.7**
    - File: `/home/michael/finance/tests/categorizer-batch-size.test.js`
    - Generator: integer N between 1 and 500
    - Assertion: `batches.length == Math.ceil(N / 50)`, no duplicates, all transactions covered

  - [ ]* 17.6 Write property test: Categorizer Failure Fallback (Property 5)
    - **Property 5: Categorizer Failure Fallback**
    - **Validates: Requirement 4.8**
    - File: `/home/michael/finance/tests/categorizer-failure-fallback.test.js`
    - Generator: arbitrary batches of 1-50 transactions
    - Assertion: all transactions get `Other` category, none left with null category_id

  - [ ]* 17.7 Write property test: Transfer Detection Correctness (Property 6)
    - **Property 6: Transfer Detection Correctness**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**
    - File: `/home/michael/finance/tests/transfer-detection.test.js`
    - Generator: random debit/credit pairs with equal absolute amounts, date offset 0-3 days, different accounts; also non-matching noise
    - Assertion: matching pairs both marked `is_transfer=true`, non-matching remain `false`

  - [ ]* 17.8 Write property test: Transfer Keyword Memo Annotation (Property 7)
    - **Property 7: Transfer Keyword Memo Annotation**
    - **Validates: Requirement 5.6**
    - File: `/home/michael/finance/tests/transfer-keyword-memo.test.js`
    - Generator: transactions with descriptions containing transfer keywords, no matching credit
    - Assertion: memo contains `"POTENTIAL TRANSFER - REVIEW NEEDED"`, `is_transfer` remains `false`

  - [ ]* 17.9 Write property test: House Tagging Keyword Correctness (Property 8)
    - **Property 8: House Tagging Keyword Correctness**
    - **Validates: Requirements 6.1, 6.5**
    - File: `/home/michael/finance/tests/house-tagging.test.js`
    - Generator: random descriptions/memos with/without house keywords, random `house_tag_manual` values
    - Assertion: keyword matches get `house_tag=true` (unless manual), non-matches get `false`, manual tags unchanged

  - [ ]* 17.10 Write property test: Budget Alert Payload Completeness (Property 9)
    - **Property 9: Budget Alert Payload Completeness and Threshold Accuracy**
    - **Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.7**
    - File: `/home/michael/finance/tests/budget-alert-payload.test.js`
    - Generator: random spending amounts and budget limits (some ≥80%, some <80%, some with no budget)
    - Assertion: alerts only for ≥80%, all payloads have required fields, `percentage_used == Math.round(amount_spent / budget_limit * 100)`

- [ ] 18. Final checkpoint — Full system validation
  - Run all property-based tests with `npx vitest --run`. Verify all webhooks respond correctly. Confirm the Budget Alert workflow fires correctly for a test category at ≥80%. Verify the Finance Workspace answers a spending question using live webhook data. Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- All n8n workflow changes are done via the n8n UI — not code files on disk
- The init SQL script is the only file written to the host filesystem (at `/home/michael/finance/init/01_init.sql`)
- Docker compose changes go through the Portainer stack editor
- n8n Code nodes cannot use `require('fs')` — use the Filewriter microservice at port 5001 for file I/O
- Postgres is NOT exposed to the host — only accessible within the Docker network at `postgres:5432`
- The `DUAL_WRITE` flag keeps JSON files flowing during migration; set to `false` only after validation
- Property tests use fast-check with vitest and test pure JavaScript functions extracted from n8n Code node logic
- The Finance Workspace system prompt documents 3-tier model routing (Opus/Sonnet/Haiku) but Sonnet is the default for initial implementation
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at each layer

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3"] },
    { "id": 4, "tasks": ["5.1", "5.2"] },
    { "id": 5, "tasks": ["6.1"] },
    { "id": 6, "tasks": ["6.2", "7.1"] },
    { "id": 7, "tasks": ["7.2", "7.3"] },
    { "id": 8, "tasks": ["9.1", "9.2", "9.3", "11.1"] },
    { "id": 9, "tasks": ["11.2", "12.1"] },
    { "id": 10, "tasks": ["13.1", "13.2"] },
    { "id": 11, "tasks": ["15.1", "15.2"] },
    { "id": 12, "tasks": ["17.1"] },
    { "id": 13, "tasks": ["17.2", "17.3", "17.4", "17.5", "17.6", "17.7", "17.8", "17.9", "17.10"] }
  ]
}
```
