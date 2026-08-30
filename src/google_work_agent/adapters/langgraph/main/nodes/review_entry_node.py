"""Canonical REVIEW_ENTRY control node."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def review_entry_node(
    state: Mapping[str, object],
    *,
    prepare_persisted_review: Callable[[Mapping[str, object]], Mapping[str, object]],
    settle_persisted_review: Callable[[Mapping[str, object]], Mapping[str, object]],
    review_node: str,
    review_logical_node: str | None = None,
) -> dict[str, object]:
    """Invoke the one Review subgraph over current persisted or pre-publish input."""

    control = state.get("__workflow_control__")
    if isinstance(control, Mapping) and control.get("stage") == "REVIEW_PENDING_SETTLEMENT":
        settled = settle_persisted_review(state)
        return {
            **{key: value for key, value in settled.items() if state.get(key) != value},
            "__workflow_control__": None,
        }

    published = isinstance(state.get("approved_plan_id"), str) and not isinstance(
        state.get("__replan_from_plan_id__"), str
    )
    already_prepared = isinstance(state.get("__modify_review_plan_id__"), str)
    working = state if not published or already_prepared else prepare_persisted_review(state)
    patch = {key: value for key, value in working.items() if state.get(key) != value}
    patch.update(
        {
            "workflow_phase": "PLAN_REVIEW",
            "__logical_target__": review_logical_node or review_node,
            "__target__": review_node,
        }
    )
    if published:
        patch["__workflow_control__"] = {
            "schema_version": 1,
            "stage": "REVIEW_PENDING_SETTLEMENT",
        }
    return patch


__all__ = ["review_entry_node"]
