"""Proactive nightly finance insight agent (ai-finance-insights Phase 1).

Detectors run read-only SQL over public.real_activity + recurring detection, emit
candidate insights with figures + a reason, and the store dedupes/ranks them. All
thresholds are DB-driven (finance.insight_config); the runner is gated on the
categorizer readiness watermark and a global kill-switch.
"""
