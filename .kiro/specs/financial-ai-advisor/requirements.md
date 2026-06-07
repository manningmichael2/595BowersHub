# Requirements Document

## Introduction

The Financial AI Advisor is an upgrade to the existing financial data pipeline on 595BowersHub. The current system pulls transactions from 17 bank accounts via SimpleFin Bridge, writes them as JSON files to disk, and serves them through an AnythingLLM Finance Workspace. This approach has a critical limitation: RAG over JSON only retrieves relevant chunks, causing the AI to miss large portions of transaction history.

This feature migrates the data layer to PostgreSQL, adds AI-assisted transaction categorization, introduces transfer detection between accounts, enables house-specific expense tracking, and delivers budget alerts — all while preserving the existing n8n workflow structure and AnythingLLM chat interface.

---

## Glossary

- **Pipeline**: The end-to-end data flow from SimpleFin Bridge → n8n → storage → AI chat
- **SimpleFin_Bridge**: The external service that syncs bank account data from 17 financial institutions
- **n8n**: The workflow automation engine running at http://100.106.180.101:5678
- **Postgres**: The PostgreSQL database container to be deployed on 595BowersHub
- **AnythingLLM**: The AI chat platform running at http://100.106.180.101:3001
- **Finance_Workspace**: The AnythingLLM workspace dedicated to financial queries
- **Filewriter**: The Flask microservice at http://100.106.180.101:5001 used for file I/O
- **Categorizer**: The n8n sub-workflow that calls the Anthropic API (Haiku) to assign a category to a transaction
- **Transfer_Detector**: The component that identifies matching debit/credit pairs across accounts as internal transfers
- **Category**: A label assigned to a transaction (e.g., Groceries, Dining, Gas, Subscriptions, Mortgage, Transfer)
- **Budget**: A monthly spending limit defined per category
- **Budget_Alert**: A notification sent when spending in a category approaches or exceeds its budget
- **House_Tag**: A flag on a transaction indicating it is related to the primary residence (595 Bowers)
- **Webhook**: An n8n HTTP endpoint that returns financial data in response to a GET request
- **Sync_Workflow**: The n8n nightly sync workflow that runs at 2am daily
- **Historical_Load**: The n8n manual workflow that loads all transactions from a configurable start date
- **Haiku**: The claude-haiku-4-5 model used for cost-efficient data processing tasks
- **Sonnet**: The claude-sonnet-4-5 model used for complex reasoning and chat responses

---

## Requirements

### Requirement 1: PostgreSQL Database Deployment

**User Story:** As Michael, I want a PostgreSQL database running on 595BowersHub, so that transaction data is stored in a structured, queryable format instead of flat JSON files.

#### Acceptance Criteria

1. THE Postgres container SHALL be deployed via Portainer as part of the existing Docker infrastructure on 595BowersHub.
2. THE Postgres database SHALL contain an `accounts` table with columns: `id`, `org_name`, `account_name`, `currency`, `last_balance`, `last_balance_date`.
3. THE Postgres database SHALL contain a `transactions` table with columns: `id`, `account_id`, `posted_date`, `amount`, `description`, `memo`, `pending`, `category_id`, `is_transfer`, `house_tag`, `created_at`.
4. THE Postgres database SHALL contain a `categories` table with columns: `id`, `name`, `budget_monthly`, `is_system`.
5. THE Postgres database SHALL contain a `budgets` table with columns: `id`, `category_id`, `month`, `limit_amount`.
6. WHEN the Postgres container starts for the first time with no existing database, THE Postgres container SHALL automatically initialize all required tables (accounts, transactions, categories, budgets) using an init SQL script mounted at container startup.
7. WHEN the Postgres container is restarted, THE Postgres database SHALL persist all data via a Docker volume mounted to the host filesystem at `/home/michael/finance/postgres-data`.
8. THE Postgres database SHALL be accessible from n8n and other Docker containers on the same Docker network via hostname `postgres` on port `5432`.

---

### Requirement 2: Data Migration — Accounts and Transactions

**User Story:** As Michael, I want all existing and future transaction data written to PostgreSQL, so that the AI can query complete financial history with SQL precision instead of RAG chunk retrieval.

#### Acceptance Criteria

1. WHEN the Historical_Load workflow is run, THE Pipeline SHALL upsert all accounts from SimpleFin_Bridge into the `accounts` table using `id` as the unique key.
2. WHEN the Historical_Load workflow is run, THE Pipeline SHALL upsert all transactions from SimpleFin_Bridge into the `transactions` table using the SimpleFin transaction `id` as the unique key.
3. WHEN the Sync_Workflow runs at 2am, THE Pipeline SHALL upsert new and updated accounts into the `accounts` table.
4. WHEN the Sync_Workflow runs at 2am, THE Pipeline SHALL upsert new and updated transactions into the `transactions` table.
5. IF a transaction already exists in the `transactions` table, THEN THE Pipeline SHALL update all SimpleFin-sourced fields (`amount`, `description`, `memo`, `pending`, `posted_date`) while leaving `category_id` and `house_tag` unchanged.
6. WHILE the `dual_write` configuration flag is set to `true`, THE Pipeline SHALL write transaction data to both PostgreSQL and JSON files at `/home/michael/finance/` on every sync, so that the existing AnythingLLM embedding workflow is not broken.
7. WHEN a transaction is upserted, THE Pipeline SHALL not overwrite `category_id` if it was manually set (indicated by `user_category_override = true`), and SHALL not overwrite `house_tag` if it was manually set (indicated by `house_tag_manual = true`).
8. IF the SimpleFin_Bridge fetch fails or the Postgres write fails during a sync, THEN THE Pipeline SHALL log the error with a timestamp and continue processing remaining accounts without aborting the entire workflow.

---

### Requirement 3: n8n Webhook Upgrade — SQL-Backed Queries

**User Story:** As Michael, I want the existing n8n webhooks to query PostgreSQL directly, so that financial data returned to the AI is complete and accurate rather than limited by JSON file chunking.

#### Acceptance Criteria

1. WHEN the balance webhook receives a GET request at `/webhook/balances`, THE Webhook SHALL return current balances for all accounts by querying the `accounts` table.
2. WHEN the date-range webhook receives a GET request at `/webhook/transactions` with `start` and `end` parameters in `YYYY-MM-DD` format, THE Webhook SHALL return all transactions in that date range by querying the `transactions` table with a SQL WHERE clause on `posted_date`.
3. WHEN the filter webhook receives a GET request at `/webhook/filter` with optional `account`, `min_amount`, `max_amount`, and `description` parameters, THE Webhook SHALL return matching transactions by querying the `transactions` table, where `description` is matched as a case-insensitive substring.
4. WHEN a webhook query is executed, THE Webhook SHALL return results within 2 seconds for queries spanning up to 24 months of data.
5. IF a webhook receives a `start` or `end` parameter that is not in `YYYY-MM-DD` format, or if `start` is after `end`, THEN THE Webhook SHALL return an HTTP 400 response with a JSON body containing a `error` field describing the specific validation failure.
6. IF a webhook receives a `min_amount` greater than `max_amount`, THEN THE Webhook SHALL return an HTTP 400 response with a JSON body containing an `error` field indicating the conflict.
7. THE Webhook SHALL support a `category` filter parameter that returns only transactions matching the specified category name using a case-insensitive exact match against the `categories.name` column.
8. IF the Postgres database is unreachable when a webhook request is received, THEN THE Webhook SHALL return an HTTP 503 response with a JSON body containing an `error` field indicating the database is unavailable.

---

### Requirement 4: AI-Assisted Transaction Categorization

**User Story:** As Michael, I want transactions to be automatically categorized using AI, so that I can track spending by category the way Monarch Money or YNAB does, without manually tagging every transaction.

#### Acceptance Criteria

1. WHEN the Sync_Workflow upserts a new transaction with no existing `category_id`, THE Categorizer SHALL call the Haiku API with the transaction `description`, `memo`, and `amount` to assign a category.
2. THE Categorizer SHALL select a category from the predefined list in the `categories` table rather than inventing new category names.
3. WHEN the Categorizer assigns a category, THE Categorizer SHALL write the `category_id` back to the `transactions` table for that transaction.
4. THE categories table SHALL be pre-seeded with at minimum the following system categories: Groceries, Dining, Gas, Transportation, Utilities, Subscriptions, Mortgage, Rent, Insurance, Medical, Shopping, Entertainment, Transfer, Income, ATM, Home_Improvement, Other.
5. WHEN the Categorizer processes a batch of transactions, THE Categorizer SHALL include up to 50 transactions per Haiku API call, sending multiple calls if the batch exceeds 50 transactions.
6. WHERE a transaction has `user_category_override = true`, THE Categorizer SHALL not update the `category_id` for that transaction on any subsequent sync or categorization run.
7. WHEN the Historical_Load workflow is run with a `categorize=true` flag, THE Categorizer SHALL process all uncategorized transactions in the `transactions` table in batches of 50.
8. IF the Haiku API call fails or times out after 30 seconds, THEN THE Categorizer SHALL assign the `Other` category to all transactions in that batch and set a flag indicating they are uncategorized, so they can be retried later.
9. IF the Haiku API returns a category name that does not exist in the `categories` table, THEN THE Categorizer SHALL assign the `Other` category to that transaction.

---

### Requirement 5: Transfer Detection Between Accounts

**User Story:** As Michael, I want the system to automatically detect transfers between my own accounts, so that internal money movements don't inflate my spending totals or confuse the AI advisor.

#### Acceptance Criteria

1. WHEN the Sync_Workflow runs, THE Transfer_Detector SHALL scan new transactions for matching debit/credit pairs across different accounts where the absolute amounts are equal and the credit transaction is posted 0 to 3 calendar days after the debit transaction.
2. WHEN a matching transfer pair is identified, THE Transfer_Detector SHALL set `is_transfer = true` on both the debit and credit transactions.
3. WHEN a matching transfer pair is identified, THE Transfer_Detector SHALL assign the `Transfer` category to both transactions.
4. WHEN multiple credit transactions match a single debit by amount and date window, THE Transfer_Detector SHALL select the credit transaction with the closest `posted_date` to the debit as the match, and leave remaining candidates unmodified.
5. WHEN the Finance_Workspace AI receives a query containing the words "spending", "expenses", "totals", or "budget", THE Finance_Workspace SHALL exclude transactions where `is_transfer = true` from all aggregations unless the query also contains the phrase "include transfers".
6. IF a new transaction's `description` or `memo` contains one of the following keywords — "Zelle", "Venmo", "ACH Transfer", "Wire Transfer", "Internal Transfer" — and no matching credit transaction is found within 3 calendar days, THEN THE Transfer_Detector SHALL set `is_transfer = false` and append "POTENTIAL TRANSFER - REVIEW NEEDED" to the transaction's `memo` field.

---

### Requirement 6: House-Specific Transaction Tracking

**User Story:** As Michael, I want to tag transactions related to the house at 595 Bowers, so that I can track home ownership costs separately from personal spending.

#### Acceptance Criteria

1. WHEN a transaction is upserted and `house_tag_manual = false`, THE Pipeline SHALL set `house_tag = true` if the transaction's `description` or `memo` contains a case-insensitive substring match against any keyword in the house keyword list; otherwise THE Pipeline SHALL set `house_tag = false`.
2. THE keyword list for house tagging SHALL be stored as a configurable JSON array in the n8n workflow, not hardcoded in application code.
3. WHEN the filter webhook receives a GET request with `house_tag=true`, THE Webhook SHALL return only transactions where `house_tag = true`, or an empty array if no such transactions exist.
4. IF the Finance_Workspace AI receives a query containing the words "house", "home", "595 Bowers", or "property", THEN THE Finance_Workspace SHALL call the filter webhook with `house_tag=true` and return a response that includes the total amount spent and the transaction count.
5. WHERE a transaction has `house_tag_manual = true`, THE Pipeline SHALL not overwrite the `house_tag` value via keyword matching logic on any subsequent upsert.

---

### Requirement 7: Budget Alerts via n8n

**User Story:** As Michael, I want to receive alerts when my spending in a category is approaching or exceeding my monthly budget, so that I can adjust my spending before going over.

#### Acceptance Criteria

1. THE n8n Budget_Alert workflow SHALL run on a daily schedule at 8am in the server's local timezone (America/New_York or as configured in the n8n environment).
2. WHEN the Budget_Alert workflow runs, THE Budget_Alert workflow SHALL query the `transactions` table for the current calendar month's spending grouped by category, excluding all transactions where `is_transfer = true`.
3. WHEN spending in a category reaches or exceeds 80% but is less than 100% of the monthly budget limit, THE Budget_Alert workflow SHALL send a notification to Michael, and SHALL NOT send a duplicate 80% alert for that category again on the same calendar day.
4. WHEN spending in a category reaches or exceeds 100% of the monthly budget limit, THE Budget_Alert workflow SHALL send a notification to Michael indicating the budget has been exceeded, and SHALL NOT send a duplicate 100% alert for that category again on the same calendar day.
5. THE Budget_Alert workflow SHALL send notifications via an HTTP POST to a configurable URL stored as an n8n environment variable, with a JSON body containing `category`, `amount_spent`, `budget_limit`, and `percentage_used` fields, compatible with ntfy.sh, Slack, or Discord webhook formats.
6. IF no budget limit is set for a category in the `budgets` table for the current month, THEN THE Budget_Alert workflow SHALL skip that category without error and without sending a notification.
7. THE Budget_Alert workflow SHALL include in each notification: the category name, amount spent, budget limit, and percentage used rounded to the nearest whole number.

---

### Requirement 8: Finance Workspace Chat Interface

**User Story:** As Michael, I want to ask natural language questions about my finances in the AnythingLLM Finance Workspace, so that I can get accurate, complete answers without manually querying the database.

#### Acceptance Criteria

1. THE Finance_Workspace system prompt SHALL instruct the AI to call the n8n webhooks to retrieve live data rather than relying on embedded documents.
2. WHEN Michael asks a spending question, THE Finance_Workspace SHALL call the filter or date-range webhook with the resolved category name and explicit `start`/`end` dates derived from the question, and return the result.
3. WHEN Michael asks about account balances, THE Finance_Workspace SHALL call the `/webhook/balances` endpoint and return balances that are no more than 24 hours stale.
4. IF a query requires aggregation across multiple accounts or date ranges, THEN THE Finance_Workspace SHALL use Sonnet to process the response. IF a query is a single-account or single-category point-in-time lookup, THEN THE Finance_Workspace SHALL use Haiku to process the response.
5. WHEN Michael asks about house expenses, THE Finance_Workspace SHALL call the filter webhook with `house_tag=true` and return a response that includes the total amount spent and the transaction count.
6. WHEN Michael asks a question that requires data spanning more than 90 days, THE Finance_Workspace SHALL use the date-range webhook rather than the filter webhook to ensure complete data retrieval.
7. IF the Finance_Workspace cannot retrieve data from a webhook, THEN THE Finance_Workspace SHALL inform Michael that the specific service (identified by its webhook path) is unavailable and suggest checking the n8n service status.

---

### Requirement 9: Auto-Embedding of Daily Sync Files

**User Story:** As Michael, I want new daily transaction files to be automatically available in AnythingLLM, so that I don't have to manually upload files after each nightly sync.

#### Acceptance Criteria

1. WHEN the Sync_Workflow completes writing a new daily JSON file, THE Sync_Workflow SHALL call the AnythingLLM API to upload and embed the new file into the Finance_Workspace.
2. WHEN the AnythingLLM embedding call succeeds, THE Sync_Workflow SHALL log an entry to the n8n execution log containing the filename and a success indication.
3. IF the AnythingLLM embedding call fails, THEN THE Sync_Workflow SHALL retry the embedding call once after a 60-second delay.
4. IF the retry also fails, THEN THE Sync_Workflow execution SHALL be marked as succeeded, and THE Sync_Workflow SHALL log an entry containing the filename, attempt count (2), and a failure indication, so that the nightly sync is not blocked by an embedding failure.

---

### Requirement 10: Data Integrity and Idempotency

**User Story:** As Michael, I want the sync workflows to be safe to re-run at any time, so that I can re-run historical loads or re-trigger syncs without creating duplicate data or corrupting existing records.

#### Acceptance Criteria

1. THE Pipeline SHALL use upsert operations (INSERT ... ON CONFLICT DO UPDATE) for all writes to the `accounts` and `transactions` tables, using the SimpleFin `id` as the conflict key.
2. WHEN the Historical_Load workflow is re-run, THE Pipeline SHALL produce the same row count and field values in the `accounts` and `transactions` tables as the first run, with no duplicate rows.
3. WHEN the Sync_Workflow is re-run for the same day, THE Pipeline SHALL produce the same row count and field values as the first run for that day, with no duplicate rows.
4. THE Pipeline SHALL not overwrite `category_id` when `user_category_override = true`, SHALL not overwrite `house_tag` when `house_tag_manual = true`, and SHALL not overwrite `is_transfer` when `is_transfer_manual = true` during any upsert operation.
5. WHEN a transaction's `amount` or `description` changes in SimpleFin_Bridge (e.g., a pending transaction settles), THE Pipeline SHALL update the existing row's SimpleFin-sourced fields rather than inserting a new row, leaving manually set fields unchanged per criterion 4.

---

### Requirement 11: Categorization User Guide and Learning Loop

**User Story:** As Michael, I want a clear guide on how to review, override, and improve AI categorization, so that I can correct mistakes and the AI gets better at categorizing my transactions over time.

#### Acceptance Criteria

1. THE system SHALL include a user guide document at `/home/michael/finance/CATEGORIZATION_GUIDE.md` explaining how to review categories, override them, and how the learning loop works.
2. WHEN the AI assigns a category automatically, THE Categorizer SHALL set `user_category_override = false`, indicating the category was AI-assigned and can be changed by the AI on future runs if the learning prompt improves.
3. WHEN Michael manually overrides a category (via SQL or a future admin interface), THE override process SHALL set `user_category_override = true` on that transaction, permanently protecting it from AI re-categorization.
4. THE Categorizer prompt SHALL include up to 50 recent manual overrides as few-shot examples, so that the AI learns Michael's categorization preferences over time (e.g., "Michael categorized 'LOWES #1234' as Home_Improvement, not Shopping").
5. THE user guide SHALL document: how to query uncategorized or miscategorized transactions, how to override a category via SQL, how to view the AI's confidence pattern, and how the learning loop feeds overrides back into the prompt.
6. WHEN the Categorizer runs, THE Categorizer SHALL query the most recent 50 transactions where `user_category_override = true` and include them as examples in the Haiku prompt to improve future categorization accuracy.

