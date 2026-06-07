# First Facts To Save — Re-Capture of May 2026 Finance Chat

The original chat used the built-in `rag-memory` skill, which we want to avoid.
This file is a structured re-capture of that blob, broken into discrete facts
to save through the `remember` skill once the system is live.

Workflow: in the AnythingLLM Finance workspace, run each block below as
`@agent remember that <fact>` (or paste the topic+fact pairs to a chat and let
the agent call `remember` for each). The agent should ask for confirmation
before saving each one — say yes if accurate, correct it if not.

## ✅ Save these — durable, low-volatility facts

### topic: finance/profile
- Michael is a 34-year-old male.
- Michael's base salary is $160,000, excluding any bonus.
- Michael does not receive a pension, RSUs, or other equity compensation.
- Michael's target retirement age is earlier than 65 (FIRE-curious).
- Michael's desired retirement lifestyle is to maintain current spending levels.

### topic: finance/retirement-strategy
- Michael maxes out his 401(k) every year ($23,500 in 2026).
- Michael maxes out a Roth IRA via the backdoor route every year ($7,000 in 2026).
- Michael maxes out his HSA on self-only coverage every year ($4,300 in 2026).
- Michael does not currently have a taxable brokerage account, which is the
  identified gap for a pre-59.5 early-retirement bridge.

### topic: finance/accounts
- PNC checking ending 0161 ("Spend") is Michael's primary checking account
  where paychecks are deposited and bills are paid.
- PNC account ending 0196 ("Growth") is for long-term savings and checking
  overflow.
- PNC account ending 0188 ("Reserve") is the checking reserve buffer.
- Ally Savings ending 8551 is part of the emergency fund and may be repurposed
  for a vacation or house fund.
- Ally Savings ending 1663 is part of the emergency fund and may be repurposed
  for savings or a house fund.
- The Credit Karma account is a credit-score tracking placeholder, not real
  money — exclude it from net-worth and balance calculations.
- The Bank of America APTIM HSA is from a former employer and is being
  transferred out (not the active HSA).
- The Bank of America GM HSA is from a former employer and is being
  transferred out (not the active HSA).
- The HealthEquity (Tenneco) HSA is the active HSA at Michael's current
  employer.
- The current HSA consolidation plan is to roll the BoA APTIM and BoA GM HSAs
  into the active HealthEquity (Tenneco) HSA.

### topic: finance/credit
- Michael's credit cards are: Chase Amazon Prime Visa, Amex Platinum,
  Citi Costco Visa.

### topic: finance/loans
- Michael's mortgage is with Rocket Mortgage on a home valued at ~$280,000.
- Michael has an Amex Personal Loan that was used for home renovations.

### topic: finance/preferences
- Net-worth and balance summaries should exclude the Credit Karma placeholder
  account and any duplicate HSA entries.

## 🤔 Confirm before saving — things to verify with Michael first

These were captured in the original blob but are worth a sanity check before
persisting. Ask the user, then save the confirmed version.

### topic: finance/retirement-strategy
- ❓ Whether Michael's current employer offers a 401(k) match, and at what %.
  The original blob assumed 5%/$8,000 unverified — do NOT save until confirmed.

### topic: finance/profile
- ❓ Tracked monthly spending (~$3,084/month / ~$37k/year) — does this include
  mortgage P&I or not? Save once Michael clarifies what's included.

## 🚫 Do NOT save these — they belong elsewhere or are ephemeral

- Account balances ($330k 401k, $12k Roth, $8,344 PNC Spend, etc.). Some of
  these live in Postgres (linked accounts via SimpleFin) and should be queried
  via `get-balances`. The unlinked ones (401k, Roth) are user-stated and will
  go stale within weeks — better captured as a periodic "401k balance update"
  fact with a date if you want longitudinal tracking, but not as a single
  point-in-time fact.
- Simulation outputs: "projected total at 65: ~$6.4M", "FI threshold $1.5M
  reachable ~age 44", "suggested $1,500/mo into taxable brokerage". These
  change with every assumption tweak. Run the simulation each time fresh.
- Default simulation assumptions (7% real, 9% nominal, 2.5% inflation). Those
  are the simulator's defaults, not facts about Michael.
- HSA "duplicate of Account 4" — this is a data-quality issue in the linked
  accounts, not a personal fact. Should be fixed in the database / SimpleFin
  side, not memorialized in knowledge.

## Notes on usage

- Treat this file as a one-time bootstrap. After running through it, future
  facts get captured organically via `@agent remember that ...` during chat.
- Once saved, you can edit the resulting markdown files in
  `/home/michael/knowledge/finance/*.md` directly if anything is wrong.
- After saving, run a few `@agent recall` queries to confirm retrieval works
  ("@agent what's my emergency fund?", "@agent what HSAs do I have?").
