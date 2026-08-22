"""Bounded confirmation-response projection shared by resumed agent owners."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.application.orchestration.contracts import (
    ConfirmationResponseV1,
    validate_confirmation_response_v1,
)


def confirmation_response_from_state(
    state: Mapping[str, object],
    *,
    owner_subgraph: str,
) -> ConfirmationResponseV1 | None:
    """Return the bounded response only to the originating resumed owner.

    Confirmation Controller stores the validated response in ``prompt_context``
    together with immutable interrupt metadata.  Downstream owners may inherit
    ``prompt_context`` through the parent graph, so owner matching is mandatory:
    a confirmation answer is never ambient cross-agent context.
    """
    prompt_context = state.get("prompt_context")
    if not isinstance(prompt_context, Mapping):
        return None
    interrupt_meta = prompt_context.get("confirmation_interrupt")
    if not isinstance(interrupt_meta, Mapping):
        return None
    if interrupt_meta.get("owner_subgraph") != owner_subgraph:
        return None
    raw = prompt_context.get("confirmation_response")
    if raw is None:
        return None
    return validate_confirmation_response_v1(cast(object, raw))


def with_confirmation_response(
    base_projection: dict[str, object],
    confirmation_response: ConfirmationResponseV1 | None,
) -> dict[str, object]:
    """Add the optional response only on a resumed owner invocation."""
    if confirmation_response is None:
        return base_projection
    return {**base_projection, "confirmation_response": dict(confirmation_response)}


__all__ = ["confirmation_response_from_state", "with_confirmation_response"]
