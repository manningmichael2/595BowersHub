"""Native smart-capture skills (n8n-decommission spec, R2.5/R2.6).

Thin wrappers auto-discovered by ``skill_registry.discover_skills()``. They read
the context the executor injects (``_user_id``, ``_workspace_id``, ``_config``,
``_model_provider``) and delegate to the engine layer, which reads the DB-driven
``smart_capture.engine`` setting per call and routes native / n8n / shadow.

Registering these under the existing skill names *is* the cutover mechanism —
dispatch is name-first, so the ``bh_skills.webhook_url`` values become inert.
"""

from backend.services.skill_registry import native_skill
from backend.services.smart_capture import engine


@native_skill("smart-capture-extract")
async def handle_extract(params: dict) -> dict:
    return await engine.run_extract(params)


@native_skill("smart-capture-commit")
async def handle_commit(params: dict) -> dict:
    return await engine.run_commit(params)


@native_skill("process-asset")
async def handle_process_asset(params: dict) -> dict:
    return await engine.run_process_asset(params)
