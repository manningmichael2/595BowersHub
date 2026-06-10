"""
SQL safety guard for ask-db.

ask-db sends LLM-generated SQL to Postgres. Before execution we (1) parse it
with sqlglot and assert it is a *single read-only SELECT*, then the caller
(2) runs it under `SET LOCAL ROLE finance_reader` in a READ ONLY transaction
with a statement_timeout. This module is layer (1): a real parser instead of
the old keyword-regex blocklist, which a crafted query could slip past.

Defense in depth — the finance_reader role already lacks privilege for the
forbidden functions and writes; this rejects them earlier with a clear reason.
"""

from __future__ import annotations

from typing import Tuple

import sqlglot
from sqlglot import exp

# Only these may be the top-level statement (pure queries).
_ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.Subquery)

# If any of these appears anywhere in the tree, reject — catches not just a
# top-level INSERT/UPDATE/etc. but also data-modifying CTEs
# (WITH x AS (DELETE ... RETURNING *) SELECT ...) and stray commands
# (SET/GRANT/VACUUM/CALL parse as exp.Command).
_DISALLOWED_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge,
    exp.Create, exp.Drop, exp.Alter, exp.Command, exp.Set,
)

# Functions that read the filesystem, run programs, do large-object or
# cross-database IO, or sleep. finance_reader can't execute these, but we
# reject them at parse time too.
_FORBIDDEN_FUNCTIONS = frozenset({
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "lo_import", "lo_export", "lo_get", "lo_put",
    "dblink", "dblink_exec",
    "pg_sleep", "pg_sleep_for", "pg_sleep_until",
    "pg_reload_conf", "pg_terminate_backend", "pg_cancel_backend",
    "set_config", "current_setting",
})


def validate_select(sql: str) -> Tuple[bool, str]:
    """Validate that `sql` is a single read-only SELECT.

    Returns (ok, reason). When ok is False, reason is a short human-readable
    explanation suitable for surfacing to the user.
    """
    sql = (sql or "").strip()
    if not sql:
        return False, "empty SQL"

    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except Exception as e:  # noqa: BLE001 — any parse failure is a rejection
        return False, f"could not parse SQL ({e})"

    if len(statements) != 1:
        return False, f"exactly one statement is allowed (found {len(statements)})"

    root = statements[0]
    if not isinstance(root, _ALLOWED_ROOTS):
        return False, f"only SELECT queries are allowed (got {type(root).__name__})"

    bad = root.find(*_DISALLOWED_NODES)
    if bad is not None:
        return False, f"non-SELECT operation is not allowed ({type(bad).__name__})"

    for fn in root.find_all(exp.Anonymous, exp.Func):
        name = (fn.name or "").lower()
        if name in _FORBIDDEN_FUNCTIONS:
            return False, f"function not allowed: {name}()"

    return True, ""
