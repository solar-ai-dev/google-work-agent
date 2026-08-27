from __future__ import annotations

import pytest

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    workspace_runtime as server,
)
from google_work_agent.application.write_approval_contracts import DEFAULT_APPROVAL_TTL_MS
from google_work_agent.application.write_claim import ClaimWriteActionService
from google_work_agent.ports.connector.claim_context_contract import (
    CLAIM_CONTEXT_DEFAULT_TTL_MS,
    CLAIM_CONTEXT_MAX_TTL_MS,
)

_SIGNING_SECRET = "application-signing-secret"
_SERVICE_INSTANCE_ID = "svc-test-1"


def _claim_service(*, ttl_ms: int | None = None) -> ClaimWriteActionService:
    kwargs: dict[str, object] = {
        "unit_of_work_factory": lambda: None,
        "now_ms": lambda: 1_000,
        "signing_secret": _SIGNING_SECRET,
        "service_instance_id": _SERVICE_INSTANCE_ID,
    }
    if ttl_ms is not None:
        kwargs["claim_ttl_ms"] = ttl_ms
    return ClaimWriteActionService(**kwargs)  # type: ignore[arg-type]


def test_application_default_claim_ttl_is_canonical_30_seconds() -> None:
    service = _claim_service()

    assert service._claim_ttl_ms == CLAIM_CONTEXT_DEFAULT_TTL_MS == 30_000
    assert server.CLAIM_CONTEXT_MAX_TTL_MS == CLAIM_CONTEXT_MAX_TTL_MS


def test_application_claim_over_60_seconds_fails_closed_before_issue() -> None:
    with pytest.raises(ValueError, match="CLAIM_CONTEXT_MAX_TTL_MS"):
        _claim_service(ttl_ms=CLAIM_CONTEXT_MAX_TTL_MS + 1)


def test_approval_ttl_is_separate_and_does_not_expand_claim_ttl() -> None:
    assert DEFAULT_APPROVAL_TTL_MS == 30 * 60 * 1000
    assert _claim_service()._claim_ttl_ms == 30_000
    assert DEFAULT_APPROVAL_TTL_MS != CLAIM_CONTEXT_DEFAULT_TTL_MS
