"""Established Local Session validation only."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.api.security.sessions import LocalSessionManager


@dataclass(frozen=True, slots=True)
class LocalSessionValidation:
    valid: bool
    compatible: bool = False
    session_digest: str | None = None


def validate_local_session(
    *,
    session_manager: LocalSessionManager,
    token: str | None,
    service_instance_id: str,
    now_ms: int,
) -> LocalSessionValidation:
    """Validate an established session without issuing or mutating one."""

    record = session_manager.resolve(
        token=token,
        service_instance_id=service_instance_id,
        now_ms=now_ms,
    )
    if record is None:
        return LocalSessionValidation(valid=False)
    return LocalSessionValidation(
        valid=True,
        compatible=record.compatible,
        session_digest=record.digest,
    )
