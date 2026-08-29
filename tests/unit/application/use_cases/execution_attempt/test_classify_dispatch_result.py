"""Canonical typed-contract and behavior gates for dispatch classification."""

from dataclasses import fields
from importlib import import_module

from google_work_agent.application.use_cases.execution_attempt.classify_dispatch_result import (
    ClassifyDispatchResultHandler,
    ClassifyDispatchResultQueryV1,
    DispatchPersistenceDecisionV1,
)
from google_work_agent.application.use_cases.execution_attempt.dispatch_connector_write import (
    DispatchConnectorWriteResultV1,
)
from google_work_agent.ports.connector.connector_write_port import ConnectorWriteResultV1


def test_canonical_application_owner_is_importable() -> None:
    assert (
        import_module(
            "google_work_agent.application.use_cases.execution_attempt.classify_dispatch_result"
        )
        is not None
    )


def test_exact_canonical_contract_fields() -> None:
    assert tuple(field.name for field in fields(ClassifyDispatchResultQueryV1)) == (
        "schema_version",
        "dispatch_result",
    )
    assert tuple(field.name for field in fields(DispatchPersistenceDecisionV1)) == (
        "schema_version",
        "disposition",
        "delivery_certainty",
        "reason_code",
    )


def test_not_sent_failure_maps_to_mark_failed_without_surrogate_result() -> None:
    connector_result = ConnectorWriteResultV1(
        schema_version=1,
        success=False,
        delivery_certainty="NOT_SENT",
        provider_request_id="request-1",
        response_metadata=None,
        error_code="CONNECTION_CLOSED",
    )

    decision = ClassifyDispatchResultHandler()(
        ClassifyDispatchResultQueryV1(
            schema_version=1,
            dispatch_result=DispatchConnectorWriteResultV1(connector_result),
        )
    )

    assert decision == DispatchPersistenceDecisionV1(
        schema_version=1,
        disposition="MARK_FAILED",
        delivery_certainty="NOT_SENT",
        reason_code="CONNECTION_CLOSED",
    )
