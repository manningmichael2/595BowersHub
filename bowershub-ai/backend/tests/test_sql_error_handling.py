"""
Property test for graceful SQL error handling in finance dashboard endpoints.

**Property 6: Graceful SQL error handling**

For any finance dashboard query, if the underlying SQL fails due to a missing
column, missing table, or schema mismatch, the endpoint SHALL return a structured
error response containing the SQL error message rather than raising an unhandled
exception or returning a 500.

**Validates: Requirements 8.4**

Feature: dashboard-integration, Property 6: Graceful SQL error handling
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st, HealthCheck

from backend.routers.dashboard import (
    finance_summary,
    finance_balances,
    finance_recent_transactions,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate random column/table names (valid SQL identifiers)
sql_identifier_strategy = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(
        whitelist_categories=("Ll", "Lu", "Nd"),
        whitelist_characters="_",
    ),
)

# Error types that simulate real Postgres SQL failures
error_type_strategy = st.sampled_from([
    "UndefinedColumn",
    "UndefinedTable",
    "SyntaxError",
    "ConnectionError",
])

# The three finance endpoints to test
FINANCE_ENDPOINTS = [finance_summary, finance_balances, finance_recent_transactions]

finance_endpoint_strategy = st.sampled_from(FINANCE_ENDPOINTS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_error_message(error_type: str, identifier: str) -> str:
    """Build a realistic SQL error message from an error type and identifier."""
    if error_type == "UndefinedColumn":
        return f'column "{identifier}" does not exist'
    elif error_type == "UndefinedTable":
        return f'relation "public.{identifier}" does not exist'
    elif error_type == "SyntaxError":
        return f'syntax error at or near "{identifier}"'
    elif error_type == "ConnectionError":
        return f"connection to server lost during query (table: {identifier})"
    return f"unknown error involving {identifier}"


def _build_mock_pool(exception: Exception) -> MagicMock:
    """
    Build a mock pool where any connection operation raises the given exception.
    Covers both .fetchrow() and .fetch() to catch all endpoint variants.
    """
    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = exception
    mock_conn.fetch.side_effect = exception

    mock_pool = MagicMock()
    mock_acquire = AsyncMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_acquire
    return mock_pool


# ---------------------------------------------------------------------------
# Property test: Graceful SQL error handling
# ---------------------------------------------------------------------------


@given(
    identifier=sql_identifier_strategy,
    error_type=error_type_strategy,
    endpoint=finance_endpoint_strategy,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@pytest.mark.asyncio
async def test_graceful_sql_error_handling(
    identifier: str, error_type: str, endpoint
) -> None:
    """
    For any finance endpoint, given any SQL error (missing column, missing
    table, syntax error, connection error), the endpoint returns a structured
    error response with {error: True, message: <non-empty string>, data: None}
    and never raises an unhandled exception.

    Feature: dashboard-integration, Property 6: Graceful SQL error handling
    """
    error_message = _build_error_message(error_type, identifier)
    exception = Exception(error_message)

    mock_pool = _build_mock_pool(exception)

    with patch("backend.routers.dashboard.get_pool", return_value=mock_pool):
        with patch(
            "backend.routers.dashboard._validate_finance_columns",
            new_callable=AsyncMock,
        ):
            # The endpoint should NEVER raise — always returns a dict
            result = await endpoint(user={"id": 1})

    # --- Assertions ---

    # 1. Response is a dict (not an exception)
    assert isinstance(result, dict), (
        f"Expected dict response, got {type(result)}"
    )

    # 2. Response has the required error structure keys
    assert "error" in result, "Response missing 'error' key"
    assert "message" in result, "Response missing 'message' key"
    assert "data" in result, "Response missing 'data' key"

    # 3. error is True (indicates failure)
    assert result["error"] is True, (
        f"Expected error=True, got {result['error']}"
    )

    # 4. message is a non-empty string containing the error text
    assert isinstance(result["message"], str), (
        f"Expected message to be str, got {type(result['message'])}"
    )
    assert len(result["message"]) > 0, "Error message should not be empty"
    assert identifier in result["message"], (
        f"Error message should contain the identifier '{identifier}', "
        f"got: '{result['message']}'"
    )

    # 5. data is None
    assert result["data"] is None, (
        f"Expected data=None, got {result['data']}"
    )


# ---------------------------------------------------------------------------
# Parametrized tests for specific SQL error scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", FINANCE_ENDPOINTS)
async def test_missing_column_error(endpoint):
    """
    Specific scenario: missing column 'posted_date' does not exist.
    All three finance endpoints handle this gracefully.
    """
    exception = Exception('column "posted_date" does not exist')
    mock_pool = _build_mock_pool(exception)

    with patch("backend.routers.dashboard.get_pool", return_value=mock_pool):
        with patch(
            "backend.routers.dashboard._validate_finance_columns",
            new_callable=AsyncMock,
        ):
            result = await endpoint(user={"id": 1})

    assert result["error"] is True
    assert "posted_date" in result["message"]
    assert result["data"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", FINANCE_ENDPOINTS)
async def test_missing_table_error(endpoint):
    """
    Specific scenario: missing table 'transactions' does not exist.
    All three finance endpoints handle this gracefully.
    """
    exception = Exception('relation "finance.transactions" does not exist')
    mock_pool = _build_mock_pool(exception)

    with patch("backend.routers.dashboard.get_pool", return_value=mock_pool):
        with patch(
            "backend.routers.dashboard._validate_finance_columns",
            new_callable=AsyncMock,
        ):
            result = await endpoint(user={"id": 1})

    assert result["error"] is True
    assert "transactions" in result["message"]
    assert result["data"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", FINANCE_ENDPOINTS)
async def test_connection_error(endpoint):
    """
    Specific scenario: connection to database lost mid-query.
    All three finance endpoints handle this gracefully.
    """
    exception = ConnectionError("connection to server at '127.0.0.1' lost")
    mock_pool = _build_mock_pool(exception)

    with patch("backend.routers.dashboard.get_pool", return_value=mock_pool):
        with patch(
            "backend.routers.dashboard._validate_finance_columns",
            new_callable=AsyncMock,
        ):
            result = await endpoint(user={"id": 1})

    assert result["error"] is True
    assert len(result["message"]) > 0
    assert result["data"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", FINANCE_ENDPOINTS)
async def test_general_runtime_error(endpoint):
    """
    Specific scenario: general RuntimeError during SQL execution.
    All three finance endpoints handle this gracefully.
    """
    exception = RuntimeError("unexpected error during query execution")
    mock_pool = _build_mock_pool(exception)

    with patch("backend.routers.dashboard.get_pool", return_value=mock_pool):
        with patch(
            "backend.routers.dashboard._validate_finance_columns",
            new_callable=AsyncMock,
        ):
            result = await endpoint(user={"id": 1})

    assert result["error"] is True
    assert "unexpected error" in result["message"]
    assert result["data"] is None
