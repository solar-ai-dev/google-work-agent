"""Classify connector delivery certainty into one durable settlement command."""

from dataclasses import dataclass
from typing import Literal

from google_work_agent.application.use_cases.execution_attempt.dispatch_connector_write import (
    DispatchConnectorWriteResultV1,
)


@dataclass(frozen=True, slots=True)
class ClassifyDispatchResultQueryV1:
    schema_version: Literal[1]
    dispatch_result: DispatchConnectorWriteResultV1


@dataclass(frozen=True, slots=True)
class DispatchPersistenceDecisionV1:
    schema_version: Literal[1]
    disposition: Literal["STORE_SUCCESS", "MARK_FAILED", "MARK_UNKNOWN_RESULT"]
    delivery_certainty: Literal["NOT_SENT", "MAY_HAVE_BEEN_SENT", "SENT_RESPONSE_LOST"] | None
    reason_code: str | None


class ClassifyDispatchResultHandler:
    def __call__(self, query: ClassifyDispatchResultQueryV1) -> DispatchPersistenceDecisionV1:
        if query.schema_version != 1:
            raise ValueError("unsupported classify dispatch query schema_version")
        result = query.dispatch_result.connector_result
        if result.success:
            disposition: Literal["STORE_SUCCESS", "MARK_FAILED", "MARK_UNKNOWN_RESULT"] = (
                "STORE_SUCCESS"
            )
        elif result.delivery_certainty == "NOT_SENT":
            disposition = "MARK_FAILED"
        else:
            disposition = "MARK_UNKNOWN_RESULT"
        return DispatchPersistenceDecisionV1(
            schema_version=1,
            disposition=disposition,
            delivery_certainty=result.delivery_certainty,
            reason_code=result.error_code,
        )


__all__ = [
    "ClassifyDispatchResultHandler",
    "ClassifyDispatchResultQueryV1",
    "DispatchPersistenceDecisionV1",
]
