"""Single Retrieval-local QueryAttempt schema authority."""

from typing import Literal, Required, TypedDict

from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    SemanticRetrievalConstraintV1,
)
from google_work_agent.ports.connector.connector_read_port import JsonValue


class ValidatedReadQuerySpecV1(TypedDict):
    tool_id: Required[str]
    tool_schema_version: Required[str]
    canonical_arguments: Required[dict[str, JsonValue]]


class QueryAttemptV1(TypedDict):
    schema_version: Required[Literal[1]]
    query_attempt_id: Required[str]
    run_id: Required[str]
    route_id: Required[str]
    round_no: Required[int]
    attempt_no: Required[int]
    resource_type: Required[str]
    connector_id: Required[str]
    operation_kind: Required[Literal["SEARCH", "NEXT_PAGE", "DETAIL_FETCH", "FREEBUSY"]]
    normalized_intent_constraints: Required[list[SemanticRetrievalConstraintV1]]
    query_spec: Required[ValidatedReadQuerySpecV1]
    previous_query_hash: Required[str | None]
    page_state_hash: Required[str | None]
    added_constraints: Required[list[str]]
    removed_constraints: Required[list[str]]
    change_reason_code: Required[str | None]
    candidate_count: Required[int | None]
    top_score: Required[float | None]
    score_margin: Required[float | None]
    confidence_band: Required[Literal["HIGH", "MEDIUM", "LOW", "NONE"] | None]
    retrieval_config_version: Required[str]
    score_config_version: Required[str]
    threshold_config_version: Required[str]
    stop_reason: Required[str | None]


__all__ = ["QueryAttemptV1", "ValidatedReadQuerySpecV1"]
