"""LangGraph-owned confirmation interrupt and bounded same-owner projection."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import asdict
from json import dumps
from typing import TYPE_CHECKING, Any, Protocol, cast

from langgraph.types import interrupt

from google_work_agent.adapters.langgraph.confirmation_llm_runtime import (
    ConfirmationAwareLLMRuntime,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESUME_CONTRACT_VERSION,
)
from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    GraphStateUpdateV1,
)
from google_work_agent.adapters.langgraph.main.supervisor import SupervisorDecisionV1
from google_work_agent.application.use_cases.run.guard_run_budget import (
    BudgetProfile,
    promote_run_budget_profile,
)
from google_work_agent.application.use_cases.run.policy_confirmation_receipt import (
    PolicyConfirmationReceiptV1,
)
from google_work_agent.application.use_cases.run.request_confirmation import (
    RequestConfirmationCommand,
    RequestConfirmationResult,
)
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
    validate_confirmation_response_projection_v1,
)
from google_work_agent.ports.system.contracts.workflow_handoff import (
    AgentNodeResumeTargetV2,
    SemanticAgentOwnerIdV1,
)

if TYPE_CHECKING:
    from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
    from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
        ResumeTargetRegistry,
    )
    from google_work_agent.ports.system.contracts.workflow_execution import (
        WorkflowStartRequest,
    )

_OWNER_RESUME_NODE: dict[SemanticAgentOwnerIdV1, str] = {
    "REQUEST_UNDERSTANDING": "request.finalize",
    "TOOL_ROUTE": "route.finalize",
    "RETRIEVAL": "retrieval.finalize",
    "WORK_ANALYSIS": "analysis.finalize",
    "PLANNING": "planning.assemble",
    "REVIEW": "review.aggregate_findings",
}


class _ConfirmationControllerSuper(Protocol):
    def _merge_decision(
        self,
        state: GraphState,
        update: GraphStateUpdateV1,
        decision: SupervisorDecisionV1,
    ) -> GraphState: ...


class ConfirmationControllerMixin:
    """Request the Domain pause before interrupt and project only validated answers."""

    if TYPE_CHECKING:
        _graph_profile: GraphProfile
        _resume_target_registry: ResumeTargetRegistry
        _request_confirmation_handler: Callable[
            [RequestConfirmationCommand], RequestConfirmationResult
        ]

        def _request_from_state(self, state: GraphState) -> WorkflowStartRequest: ...

        def _required_string(self, value: object, field_name: str) -> str: ...

        def _current_run_version(self, run_id: str) -> int: ...

        def _current_run_status(self, run_id: str) -> str: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        llm_runtime = kwargs.get("llm_runtime")
        if llm_runtime is None:
            raise TypeError("llm_runtime is required")
        confirmation_llm_runtime = ConfirmationAwareLLMRuntime(llm_runtime)
        kwargs["llm_runtime"] = confirmation_llm_runtime
        self._confirmation_llm_runtime = confirmation_llm_runtime
        super().__init__(*args, **kwargs)

    def _merge_decision(
        self,
        state: GraphState,
        update: GraphStateUpdateV1,
        decision: SupervisorDecisionV1,
    ) -> GraphState:
        merged = cast(_ConfirmationControllerSuper, super())._merge_decision(
            state, update, decision
        )
        return self._clear_consumed_confirmation(state=state, merged=merged)

    def _clear_consumed_confirmation(self, *, state: GraphState, merged: GraphState) -> GraphState:
        prompt_context = state.get("prompt_context")
        if not isinstance(prompt_context, Mapping) or "confirmation_response" not in prompt_context:
            return merged
        run_id = state.get("run_id")
        if isinstance(run_id, str):
            self._confirmation_llm_runtime.clear(run_id=run_id)
        next_prompt_context = dict(cast(Mapping[str, object], merged.get("prompt_context", {})))
        next_prompt_context.pop("confirmation_response", None)
        next_prompt_context.pop("confirmation_interrupt", None)
        merged["prompt_context"] = next_prompt_context
        merged["retry_budget"] = promote_run_budget_profile(
            merged["retry_budget"], BudgetProfile.REVISION_HEAVY
        )
        return merged

    def _confirm_request_understanding_inline(
        self, state: GraphState
    ) -> tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]:
        return self._confirm_owner_inline(state, semantic_owner_id="REQUEST_UNDERSTANDING")

    def _confirm_context_retrieval_inline(
        self, state: GraphState
    ) -> tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]:
        return self._confirm_owner_inline(state, semantic_owner_id="RETRIEVAL")

    def _confirm_tool_route_inline(
        self, state: GraphState
    ) -> tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]:
        return self._confirm_owner_inline(state, semantic_owner_id="TOOL_ROUTE")

    def _confirm_work_analysis_inline(
        self, state: GraphState
    ) -> tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]:
        return self._confirm_owner_inline(state, semantic_owner_id="WORK_ANALYSIS")

    def _confirm_planning_inline(
        self, state: GraphState
    ) -> tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]:
        return self._confirm_owner_inline(state, semantic_owner_id="PLANNING")

    def _confirm_review_inline(
        self, state: GraphState
    ) -> tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]:
        return self._confirm_owner_inline(state, semantic_owner_id="REVIEW")

    def _confirm_owner_inline(
        self,
        state: GraphState,
        *,
        semantic_owner_id: SemanticAgentOwnerIdV1,
    ) -> tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]:
        request = self._request_from_state(state)
        raw_interrupt = state.get("user_interrupt")
        if not isinstance(raw_interrupt, Mapping):
            raise ValueError("confirmation user_interrupt is missing")
        interrupt_id = self._required_string(raw_interrupt.get("interrupt_id"), "interrupt_id")
        target = self._resume_target_registry.issue_agent_node(
            self._graph_profile.value,
            semantic_owner_id,
            _OWNER_RESUME_NODE[semantic_owner_id],
            RESUME_CONTRACT_VERSION,
        )
        requested = self._request_confirmation_handler(
            RequestConfirmationCommand(
                run_id=request.run_id,
                expected_version=int(self._current_run_version(request.run_id)),
                interrupt_id=interrupt_id,
                request_hash=_request_hash(request.run_id, interrupt_id, semantic_owner_id, target),
                semantic_owner_id=semantic_owner_id,
                resume_target=target,
            )
        )
        if not requested.applied:
            return None, {
                "__target__": "end",
                "__workflow_control__": {
                    "schema_version": 1,
                    "stage": "CONFIRMATION_SUSPENDED",
                    "result": "REQUEST_CONFIRMATION_NOT_APPLIED",
                    "result_code": requested.result_code,
                },
            }

        raw_resume = interrupt(
            {
                "interrupt_kind": "CONFIRMATION",
                "run_id": request.run_id,
                **dict(raw_interrupt),
                "semantic_owner_id": semantic_owner_id,
                "resume_target": asdict(target),
                "pre_confirmation_status": requested.pre_confirmation_status,
                "checkpoint_id": requested.checkpoint_id,
                "checkpoint_generation": requested.checkpoint_generation,
            }
        )
        if not isinstance(raw_resume, Mapping):
            raise ValueError("confirmation resume control must be an object")
        response = validate_confirmation_response_projection_v1(
            raw_resume.get("confirmation_response")
        )
        self._validate_confirmation_option_scope(
            interrupt_payload=raw_interrupt,
            response=response,
        )
        if self._current_run_status(request.run_id) != requested.pre_confirmation_status:
            return None, {
                "__target__": "end",
                "__workflow_control__": {
                    "schema_version": 1,
                    "stage": "CONFIRMATION_SUSPENDED",
                    "result": "CONFIRMATION_RESUME_CONFLICT",
                },
            }
        self._materialize_policy_receipt_projection(state, raw_resume)
        # A resumed Product Prompt is a revision-heavy route. Promotion is
        # monotonic and preserves every already-consumed call/counter.
        state["retry_budget"] = promote_run_budget_profile(
            state["retry_budget"], BudgetProfile.REVISION_HEAVY
        )
        origin_target = self._required_string(raw_interrupt.get("origin_target"), "origin_target")
        self._confirmation_llm_runtime.register(
            run_id=request.run_id,
            origin_target=origin_target,
            response=response,
        )
        prompt_context = dict(cast(Mapping[str, object], state.get("prompt_context", {})))
        prompt_context["confirmation_interrupt"] = {
            "semantic_owner_id": semantic_owner_id,
            "origin_target": origin_target,
        }
        prompt_context["confirmation_response"] = dict(response)
        state["prompt_context"] = prompt_context
        return response, None

    @staticmethod
    def _materialize_policy_receipt_projection(
        state: GraphState, raw_resume: Mapping[str, object]
    ) -> None:
        raw_receipt = raw_resume.get("policy_confirmation_receipt")
        if raw_receipt is None:
            return
        if not isinstance(raw_receipt, dict):
            raise ValueError("policy confirmation receipt projection is invalid")
        receipts = list(
            cast(list[PolicyConfirmationReceiptV1], state.get("policy_confirmation_receipts", []))
        )
        receipts.append(cast(PolicyConfirmationReceiptV1, raw_receipt))
        state["policy_confirmation_receipts"] = receipts

    @staticmethod
    def _validate_confirmation_option_scope(
        *,
        interrupt_payload: Mapping[str, object],
        response: ConfirmationResponseProjectionV1,
    ) -> None:
        raw_options = interrupt_payload.get("options", [])
        if not isinstance(raw_options, list):
            raise ValueError("confirmation options must be a list")
        allowed_ids = {
            option["option_id"]
            for option in raw_options
            if isinstance(option, Mapping)
            and isinstance(option.get("option_id"), str)
            and option["option_id"]
        }
        if response["response_kind"] == "OPTION":
            if response["selected_option"] not in allowed_ids:
                raise ValueError("selected_option is outside the interrupt options")
        elif response["response_kind"] == "FREE_TEXT" and allowed_ids:
            raise ValueError("closed-choice confirmation requires OPTION or DECLINE")


def _request_hash(
    run_id: str,
    interrupt_id: str,
    owner: SemanticAgentOwnerIdV1,
    target: AgentNodeResumeTargetV2,
) -> str:
    payload = dumps(
        {
            "run_id": run_id,
            "interrupt_id": interrupt_id,
            "semantic_owner_id": owner,
            "resume_target": asdict(target),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = ["ConfirmationControllerMixin"]
