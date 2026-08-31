"""Project the latest failed delivery certainty for one Action."""

from __future__ import annotations

from json import JSONDecodeError, loads
from typing import Literal

from google_work_agent.application.use_cases.execution_attempt.persistence_projection import (
    latest_attempt_for_action,
)
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

DeliveryCertaintyV1 = Literal["NOT_SENT", "MAY_HAVE_BEEN_SENT", "SENT_RESPONSE_LOST"]


def project_latest_delivery_certainty(
    unit_of_work: UnitOfWork,
    action_id: str,
) -> DeliveryCertaintyV1 | None:
    attempt = latest_attempt_for_action(unit_of_work, action_id)
    if attempt is None or attempt.status not in {
        ExecutionAttemptStatusV1.FAILED,
        ExecutionAttemptStatusV1.UNKNOWN_RESULT,
    }:
        return None
    raw = attempt.response_metadata_json
    if not isinstance(raw, str):
        return None
    try:
        metadata = loads(raw)
    except (JSONDecodeError, TypeError):
        return None
    if not isinstance(metadata, dict):
        return None
    certainty = metadata.get("delivery_certainty")
    if certainty in {"NOT_SENT", "MAY_HAVE_BEEN_SENT", "SENT_RESPONSE_LOST"}:
        return certainty
    return None


__all__ = ["DeliveryCertaintyV1", "project_latest_delivery_certainty"]
