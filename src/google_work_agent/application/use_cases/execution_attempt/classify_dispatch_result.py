"""Classify connector delivery certainty into one durable settlement command."""

from dataclasses import dataclass
from typing import Literal

from google_work_agent.ports.connector.connector_write_port import ConnectorWriteResultV1


@dataclass(frozen=True, slots=True)
class ClassifyDispatchResultQueryV1:
    dispatch_result: ConnectorWriteResultV1


@dataclass(frozen=True, slots=True)
class DispatchPersistenceDecisionV1:
    decision: Literal["STORE_SUCCESS", "MARK_FAILED", "MARK_UNKNOWN_RESULT"]
    result: ConnectorWriteResultV1


class ClassifyDispatchResultHandler:
    def __call__(self, query: ClassifyDispatchResultQueryV1) -> DispatchPersistenceDecisionV1:
        result = query.dispatch_result
        if result.success:
            decision: Literal["STORE_SUCCESS", "MARK_FAILED", "MARK_UNKNOWN_RESULT"] = (
                "STORE_SUCCESS"
            )
        elif result.delivery_certainty == "NOT_SENT":
            decision = "MARK_FAILED"
        else:
            decision = "MARK_UNKNOWN_RESULT"
        return DispatchPersistenceDecisionV1(decision, result)


__all__ = [
    "ClassifyDispatchResultHandler",
    "ClassifyDispatchResultQueryV1",
    "DispatchPersistenceDecisionV1",
]
