"""Application policy for aggregating readiness checks."""

from __future__ import annotations

from google_work_agent.ports import (
    ReadinessCheckResult,
    ReadinessReport,
    ReadinessState,
)


def compose_readiness(checks: tuple[ReadinessCheckResult, ...]) -> ReadinessReport:
    """Derive aggregate readiness from individual check states."""

    if any(check.state is ReadinessState.SAFE_MODE for check in checks):
        state = ReadinessState.SAFE_MODE
    elif any(check.state is ReadinessState.NOT_READY for check in checks):
        state = ReadinessState.NOT_READY
    elif checks and all(check.state is ReadinessState.READY for check in checks):
        state = ReadinessState.READY
    else:
        state = ReadinessState.NOT_CONFIGURED
    return ReadinessReport(state=state, checks=checks)
