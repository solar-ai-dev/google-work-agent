"""Project current-Run evidence available to approval-gated write actions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypedDict, cast

from google_work_agent.adapters.langgraph.main.state import request_from_state
from google_work_agent.adapters.system.memory.retrieval_evidence_store import (
    resolve_evidence_projection,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    RetrievalResultV1,
)


class UserMessageEvidenceDraftV1(TypedDict):
    schema_version: Literal[1]
    evidence_id: str
    origin_type: Literal["USER_MESSAGE"]
    message_id: str
    kind: Literal["USER_REQUEST"]
    excerpt: str


type ActionEvidenceDraftV1 = dict[str, object]


def project_current_action_evidence(
    *, state: Mapping[str, object], evidence_store: Any
) -> list[ActionEvidenceDraftV1]:
    """Join Retrieval evidence with the current Run's persisted USER Message.

    The user message is an existing Domain evidence origin, not a synthetic
    Connector resource. Its durable message identity lets CREATE actions remain
    grounded without inventing a ResourceRef or weakening the one-evidence rule.
    """

    run_id = state.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("action evidence projection requires run_id")

    result: list[ActionEvidenceDraftV1] = []
    retrieval_result = state.get("retrieval_result")
    if retrieval_result is not None:
        if not isinstance(retrieval_result, Mapping):
            raise TypeError("retrieval_result must be an object")
        result.extend(
            dict(item)
            for item in resolve_evidence_projection(
                store=evidence_store,
                run_id=run_id,
                retrieval_result=cast(RetrievalResultV1, retrieval_result),
            )
        )

    request = request_from_state(state)
    if request.run_id != run_id:
        raise ValueError("workflow request does not belong to current Run")
    if request.user_message_id is not None:
        if not request.user_message_id:
            raise ValueError("current Run user_message_id must not be empty")
        user_evidence: UserMessageEvidenceDraftV1 = {
            "schema_version": 1,
            "evidence_id": request.user_message_id,
            "origin_type": "USER_MESSAGE",
            "message_id": request.user_message_id,
            "kind": "USER_REQUEST",
            "excerpt": request.request_text,
        }
        if any(item.get("evidence_id") == request.user_message_id for item in result):
            raise ValueError("user message evidence identity collides with Retrieval evidence")
        result.append(dict(user_evidence))
    return result


__all__ = [
    "ActionEvidenceDraftV1",
    "UserMessageEvidenceDraftV1",
    "project_current_action_evidence",
]
