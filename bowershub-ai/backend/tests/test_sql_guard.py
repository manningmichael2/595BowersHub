"""Unit tests for the ask-db SQL guard (single read-only SELECT validation)."""

import pytest

from backend.services.sql_guard import validate_select


ALLOWED = [
    "SELECT 1",
    "SELECT sum(amount) FROM finance.transactions WHERE amount < 0",
    "select * from inventory.tools limit 10",
    "WITH t AS (SELECT * FROM finance.transactions) SELECT count(*) FROM t",
    "SELECT 1 UNION SELECT 2",
    "SELECT a FROM finance.accounts EXCEPT SELECT a FROM finance.budgets",
    "SELECT category, SUM(ABS(amount)) FROM finance.transactions GROUP BY category",
]

REJECTED = [
    "",
    "INSERT INTO finance.transactions(id) VALUES (1)",
    "UPDATE finance.accounts SET balance = 0",
    "DELETE FROM finance.transactions",
    "DROP TABLE finance.transactions",
    "TRUNCATE finance.transactions",
    "ALTER TABLE finance.accounts ADD COLUMN x int",
    "GRANT SELECT ON finance.accounts TO finance_reader",
    "SET ROLE postgres",
    # multiple statements / stacked queries
    "SELECT 1; DROP TABLE finance.transactions",
    "SELECT 1; SELECT 2",
    # data-modifying CTE that still "looks like" a SELECT
    "WITH d AS (DELETE FROM finance.transactions RETURNING *) SELECT * FROM d",
    # filesystem / program / sleep functions
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT pg_ls_dir('/')",
    "SELECT lo_import('/etc/passwd')",
    "SELECT pg_sleep(10)",
    # not parseable
    "this is not sql",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows_read_only_selects(sql):
    ok, reason = validate_select(sql)
    assert ok, f"expected allowed, got rejected: {reason!r} for {sql!r}"


@pytest.mark.parametrize("sql", REJECTED)
def test_rejects_non_selects_and_dangerous(sql):
    ok, reason = validate_select(sql)
    assert not ok, f"expected rejected but was allowed: {sql!r}"
    assert reason  # a human-readable reason is always provided
