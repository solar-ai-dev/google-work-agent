"""Execution-attempt-owner values for write dispatch orchestration."""

from dataclasses import dataclass

from google_work_agent.application.use_cases.claim.build_claim_context import ClaimContextV2


@dataclass(frozen=True, slots=True)
class PreparedWriteDispatch:
    tool_name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class AuthorizedWriteDispatch:
    prepared: PreparedWriteDispatch
    claim_context: ClaimContextV2


__all__ = ["AuthorizedWriteDispatch", "PreparedWriteDispatch"]
