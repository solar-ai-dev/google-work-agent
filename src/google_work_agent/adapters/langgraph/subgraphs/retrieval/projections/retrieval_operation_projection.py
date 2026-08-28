"""Allowlisted projection of one Retrieval operation input."""

from __future__ import annotations

from collections.abc import Mapping

_ALLOWED = frozenset(
    {
        "plan_query",
        "build_query",
        "execute_read",
        "normalize_segments",
        "rag_retrieve_rerank",
        "select_evidence",
        "assess_sufficiency",
        "finalize_retrieval",
    }
)


def project_retrieval_operation_input(
    state: Mapping[str, object], operation: str
) -> dict[str, object]:
    if operation not in _ALLOWED:
        raise ValueError(f"unknown retrieval operation: {operation}")
    inputs = state.get("operation_inputs")
    if not isinstance(inputs, Mapping):
        raise ValueError("retrieval operation_inputs are required")
    value = inputs.get(operation)
    if not isinstance(value, Mapping):
        raise ValueError(f"missing typed input projection for retrieval.{operation}")
    return dict(value)
