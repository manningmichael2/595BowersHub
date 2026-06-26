"""T-AUDIT-1 — mechanical "zero ungated route" audit (design §Risks).

Introspects the FastAPI route table built from every backend.routers module and
asserts:
  - EVERY route (read or write) under /api/db carries a require_capability /
    require_role dependency (B1: the hole there was a GET export); and
  - EVERY mutating route (POST/PUT/PATCH/DELETE) under /api/finance, /api/retirement,
    /api/admin is gated the same way.
A route whose only auth is a bare get_current_user FAILS — the "zero ungated"
metric made executable so a future endpoint can't silently regress.

No DB / network: this is pure route-table reflection.
"""

from __future__ import annotations

import importlib
import pkgutil

from fastapi import FastAPI
from fastapi.routing import APIRoute

import backend.routers as routers_pkg


# Dependency callables that constitute "gated". require_admin == require_role("admin")
# whose inner closure is _require_role; require_capability's inner is _require_capability.
GATE_CALLABLES = {"_require_capability", "_require_role"}
BARE_AUTH = {"get_current_user"}

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def _build_app() -> FastAPI:
    """Include the `router` from every backend.routers.* module (skip any that
    can't import cleanly in the test env). Mirrors the real app's route surface
    without importing main.py (which touches the filesystem at import)."""
    app = FastAPI()
    for mod in pkgutil.iter_modules(routers_pkg.__path__):
        try:
            m = importlib.import_module(f"backend.routers.{mod.name}")
        except Exception:
            continue
        router = getattr(m, "router", None)
        if router is not None:
            app.include_router(router)
    return app


def _gate_callable_names(route: APIRoute) -> set[str]:
    """All dependency callables on a route, recursively (names only)."""
    names: set[str] = set()

    def walk(dependant):
        if getattr(dependant, "call", None) is not None:
            names.add(getattr(dependant.call, "__name__", ""))
        for sub in getattr(dependant, "dependencies", []):
            walk(sub)

    walk(route.dependant)
    return names


def _is_gated(route: APIRoute) -> bool:
    return bool(_gate_callable_names(route) & GATE_CALLABLES)


def _in_scope(route: APIRoute) -> bool:
    path = route.path
    if path.startswith("/api/db"):
        return True  # every method, read or write (B1)
    if path.startswith(("/api/finance", "/api/retirement", "/api/admin")):
        return bool(set(route.methods or set()) & MUTATING)
    return False


def test_no_ungated_finance_admin_or_db_routes():
    app = _build_app()
    offenders = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not _in_scope(route):
            continue
        if not _is_gated(route):
            methods = ",".join(sorted(route.methods or []))
            offenders.append(f"{methods} {route.path} (deps: {sorted(_gate_callable_names(route))})")
    assert not offenders, (
        "Ungated in-scope routes (bare get_current_user / no auth) — every finance/"
        "admin mutation and every /api/db route must carry require_capability/"
        "require_role:\n  " + "\n  ".join(offenders)
    )


def test_db_browser_routes_are_all_gated():
    """Sharper sub-check: a representative /api/db read endpoint is gated (B1)."""
    app = _build_app()
    db_routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/api/db")]
    assert db_routes, "expected /api/db routes to be present in the audited app"
    ungated = [r.path for r in db_routes if not _is_gated(r)]
    assert not ungated, f"/api/db routes on bare auth: {ungated}"


def test_audit_detects_a_planted_ungated_route():
    """Negative control — the audit must FAIL a deliberately ungated finance
    mutation, proving it has teeth (not vacuously green)."""
    from backend.middleware.auth import get_current_user
    from fastapi import Depends

    app = _build_app()

    @app.post("/api/finance/_audit_canary")
    async def _canary(user: dict = Depends(get_current_user)):  # bare auth on purpose
        return {}

    offenders = [
        r.path for r in app.routes
        if isinstance(r, APIRoute) and _in_scope(r) and not _is_gated(r)
    ]
    assert "/api/finance/_audit_canary" in offenders
