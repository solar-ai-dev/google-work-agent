"""Validation-only owner for legacy fused-profile context result inputs."""

from __future__ import annotations

from functools import partial
from typing import cast

import google_work_agent.application.agents.retrieval.contracts.schema_validation as _schema
from evaluation.compat.legacy_agent_workflow import (
    ContextResult,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    ContextRetrievalResultV1,
)
from google_work_agent.application.agents.retrieval.normalize_segments import (
    ContextRetrievalValidationError,
)
from google_work_agent.ports.system.contracts.additional_acquisition import (
    validate_additional_acquisition_request_v1,
)

_CONTEXT_RESULT_VALUES = {item.value for item in ContextResult}


def validate_context_retrieval_result_v1(value: object) -> ContextRetrievalResultV1:
    """Validate the historical fused-profile DTO without owning Retrieval behavior."""
    root = _require_mapping(value, "$")
    _require_exact_keys(
        root,
        "$",
        {
            "schema_version",
            "status",
            "context_bundle",
            "evidence_drafts",
            "selected_segment_ids",
            "excluded_resource_handles",
            "missing_slots",
            "additional_acquisition_request",
            "sufficiency",
            "llm_provider_result",
        },
    )
    _require_schema_version(root, "$")
    status = _require_string(root, "status", "$")
    if status not in _CONTEXT_RESULT_VALUES:
        raise ContextRetrievalValidationError("$.status is invalid")
    result = cast(ContextRetrievalResultV1, root)
    request = _nullable_mapping(
        root["additional_acquisition_request"],
        "$.additional_acquisition_request",
    )
    if request is not None:
        result["additional_acquisition_request"] = validate_additional_acquisition_request_v1(
            request,
            allowed_evidence_refs=set(result["context_bundle"]["evidence_refs"]),
        )
    _validate_result_invariant(result)
    return result


def _validate_result_invariant(result: ContextRetrievalResultV1) -> None:
    status = ContextResult(result["status"])
    request = result["additional_acquisition_request"]
    if status is ContextResult.NEEDS_MORE_DATA and request is None:
        raise ContextRetrievalValidationError(
            "NEEDS_MORE_DATA requires additional_acquisition_request"
        )
    if status is not ContextResult.NEEDS_MORE_DATA and request is not None:
        raise ContextRetrievalValidationError(
            "additional_acquisition_request is only allowed for NEEDS_MORE_DATA"
        )


_require_mapping = partial(_schema.require_mapping, error_cls=ContextRetrievalValidationError)
_nullable_mapping = partial(_schema.nullable_mapping, error_cls=ContextRetrievalValidationError)
_require_exact_keys = partial(_schema.require_exact_keys, error_cls=ContextRetrievalValidationError)
_require_string = partial(_schema.require_string, error_cls=ContextRetrievalValidationError)
_require_schema_version = partial(
    _schema.require_schema_version,
    expected=1,
    error_cls=ContextRetrievalValidationError,
)

__all__ = ["validate_context_retrieval_result_v1"]
