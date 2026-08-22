"""Atomic Review inspection contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol, TypedDict


ReviewDimension = Literal["GOAL_EVIDENCE", "ACTION_SCOPE_ROUTE", "CONSTRAINTS_POLICY"]


class AtomicReviewFindingV1(TypedDict):
    dimension: ReviewDimension
    code: str
    description: str
    action_id: str | None
    route_id: str | None
    required_information: list[str]


class ReviewSemanticInvoker(Protocol):
    def __call__(
        self,
        prompt_id: str,
        prompt_input: Mapping[str, object],
    ) -> Mapping[str, object]: ...
