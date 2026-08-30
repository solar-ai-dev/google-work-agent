"""Canonical two-node Planning ANSWER graph and production path binding."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from langchain_core.runnables import RunnableBranch
from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.agent_kernel import (
    build_agent_local_state,
    consume_llm_call_budget,
    ensure_llm_call_budget,
    merge_trace_context,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESPONSE_SYNTHESIS_TARGET,
)
from google_work_agent.adapters.langgraph.main.state import (
    PLANNING_AGENT_LOCAL_KEY,
    request_from_state,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.compose_answer_node import (
    compose_answer_node,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.outline_answer_node import (
    outline_answer_node,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.routing import (
    route_after_compose_answer as compose_answer_routing,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.routing import (
    route_after_outline_answer as outline_answer_routing,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.state import PlanningState
from google_work_agent.application.agents.planning.choose_answer_or_action_from_route import (
    choose_answer_or_action_from_route,
)
from google_work_agent.application.agents.planning.compose_answer import (
    ANSWER_DRAFT_CANDIDATE_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.planning.outline_answer import (
    ANSWER_OUTLINE_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    OutputToolRouteV1,
    output_routes,
)
from google_work_agent.application.orchestration.confirmation import build_user_interrupt_v1
from google_work_agent.application.orchestration.contracts import (
    ConfirmationResponseProjectionV1,
    GraphStateUpdateV1,
    WorkflowPhase,
    approve_planning_revision,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    ClarificationQuestionV1,
    EvidenceDraftV1,
    StateArtifactRefV1,
)
from google_work_agent.application.orchestration.planning_argument_orchestrator import (
    RouteArgumentResult,
)
from google_work_agent.application.orchestration.retrieval_evidence_store import (
    RunScopedEvidenceStore,
    resolve_evidence_projection,
)
from google_work_agent.application.orchestration.supervisor import SupervisorDecisionV1
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.llm import (
    OutputSchemaDefinition,
    PromptReference,
    StructuredLLMResult,
)
from google_work_agent.ports.system.contracts.observability import ObservabilityContext

MergeDecision = Callable[[Any, GraphStateUpdateV1, object], Any]
ConfirmInline = Callable[
    [Mapping[str, object]],
    tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None],
]


@dataclass(frozen=True, slots=True)
class PlanningRuntimeDependencies:
    """Injected semantic callable used by focused tests and in-process consumers."""

    invoke: PlanningSemanticInvoker


def planning_answer_path_selected(state: Mapping[str, object]) -> bool:
    """Apply the frozen-route decision without materializing a branch Runtime Node."""
    raw_plan = state.get("tool_route_plan")
    if not isinstance(raw_plan, Mapping):
        raise ValueError("tool_route_plan is required")
    disposition = choose_answer_or_action_from_route(raw_plan)
    if disposition == "ANSWER":
        return True
    analysis = state.get("work_analysis", state.get("work_analysis_result"))
    return isinstance(analysis, Mapping) and analysis.get("action_necessity") == "NOT_REQUIRED"


def build_production_planning_runtime(
    *, answer: Any, action_delegate: Any
) -> RunnableBranch[Any, Any]:
    """Keep only ACTION on the temporary #118 delegate; ANSWER uses the exact graph."""
    return RunnableBranch(
        (lambda state: planning_answer_path_selected(cast(Mapping[str, object], state)), answer),
        action_delegate,
    )


class PlanningSubgraph:
    """Execute only planning.outline_answer -> planning.compose_answer."""

    def __init__(
        self,
        *,
        dependencies: PlanningRuntimeDependencies | None = None,
        llm_runtime: StructuredLLMRuntime | None = None,
        prompt_manifest_path: Path | None = None,
        id_factory: Callable[[], str] | None = None,
        graph_profile: GraphProfile | None = None,
        merge_decision: MergeDecision | None = None,
        evidence_store: RunScopedEvidenceStore | None = None,
        confirm_inline: ConfirmInline | None = None,
        **_integration: Any,
    ) -> None:
        if dependencies is not None and llm_runtime is not None:
            raise ValueError("supply either PlanningRuntimeDependencies or llm_runtime")
        self._dependencies = dependencies
        self._llm_runtime = llm_runtime
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._merge_decision = merge_decision
        self._evidence_store = evidence_store
        self._confirm_inline = confirm_inline
        self._prompt_refs: dict[str, PromptReference] = {}
        if llm_runtime is not None:
            manifest = prompt_manifest_path or default_prompt_manifest_path()
            self._prompt_refs = {
                "planning.outline_answer": load_prompt_reference(
                    "planning.outline_answer", manifest
                ),
                "planning.compose_answer": load_prompt_reference(
                    "planning.compose_answer", manifest
                ),
            }

    def build(self) -> Any:
        graph = StateGraph(PlanningState)
        graph.add_node("outline_answer", self._outline_answer_node)
        graph.add_node("compose_answer", self._compose_answer_node)
        graph.add_conditional_edges(
            START,
            self._route_at_entry,
            {"outline_answer": "outline_answer"},
        )
        graph.add_conditional_edges(
            "outline_answer",
            outline_answer_routing.route_after_outline_answer,
            {"compose_answer": "compose_answer"},
        )
        graph.add_conditional_edges(
            "compose_answer",
            compose_answer_routing.route_after_compose_answer,
            {"outline_answer": "outline_answer", "end": END},
        )
        return graph.compile(name="planning_answer_subgraph")

    @staticmethod
    def _route_at_entry(state: PlanningState) -> str:
        if not planning_answer_path_selected(cast(Mapping[str, object], state)):
            raise ValueError("ACTION Planning is delegated to the #118 runtime")
        return "outline_answer"

    def _outline_answer_node(self, state: PlanningState) -> PlanningState:
        working = self._project_runtime_inputs(state)
        if self._llm_runtime is not None:
            ensure_llm_call_budget(cast(Any, working))
        patch = outline_answer_node(
            cast(Mapping[str, object], working),
            invoke=self._semantic_invoker(state),
        )
        result = cast(
            PlanningState,
            {
                **patch,
                "planning_disposition": "ANSWER",
                "__planning_retry_outline__": False,
                **(
                    {"planning_confirmation": None}
                    if "answer_outline" in patch
                    else self._confirmation_patch(state, patch["planning_confirmation"])
                ),
            },
        )
        if self._llm_runtime is not None:
            if not isinstance(state.get(PLANNING_AGENT_LOCAL_KEY), Mapping):
                assert self._id_factory is not None
                result[PLANNING_AGENT_LOCAL_KEY] = build_agent_local_state(
                    agent_role="planning",
                    invocation_id=self._id_factory(),
                    node_state="OUTLINE_COMPLETE",
                    input_projection={"route": "ANSWER"},
                    prompt_ref=self._prompt_refs["planning.outline_answer"],
                )
            trace_state = cast(PlanningState, {**state, **result})
            result["retry_budget"] = consume_llm_call_budget(cast(Any, state))
            result["trace_context"] = self._trace(
                trace_state,
                "outline_answer",
                self._prompt_refs["planning.outline_answer"],
                first=not isinstance(state.get(PLANNING_AGENT_LOCAL_KEY), Mapping),
            )
        return result

    def _compose_answer_node(self, state: PlanningState) -> PlanningState:
        if isinstance(state.get("planning_confirmation"), Mapping):
            return self._resolve_confirmation(state)
        working = self._project_runtime_inputs(state)
        if self._llm_runtime is not None:
            ensure_llm_call_budget(cast(Any, working))
        patch = compose_answer_node(
            cast(Mapping[str, object], working),
            invoke=self._semantic_invoker(state),
        )
        candidate = cast(dict[str, object], patch["answer_draft"])
        if not self._is_production_integration:
            return cast(
                PlanningState,
                {**patch, "final_result": candidate, "planning_disposition": "ANSWER"},
            )

        answer = self._materialize_answer(state, candidate)
        assert self._merge_decision is not None
        decision: SupervisorDecisionV1 = {
            "target": RESPONSE_SYNTHESIS_TARGET,
            "next_phase": WorkflowPhase.RESPONSE_SYNTHESIS.value,
            "state_update": cast(
                GraphStateUpdateV1,
                {
                    "workflow_phase": WorkflowPhase.RESPONSE_SYNTHESIS.value,
                    "answer_draft": answer,
                    "planning_result": answer,
                    "workflow_signal": None,
                    "user_interrupt": None,
                    "finalize_intent": None,
                },
            ),
            "reason_code": "ANSWER_ONLY_RESPONSE_READY",
            "budget_decision": None,
        }
        update = cast(
            GraphStateUpdateV1,
            {
                "answer_draft": answer,
                "planning_result": answer,
                "retry_budget": consume_llm_call_budget(cast(Any, state)),
                "trace_context": self._trace(
                    state, "compose_answer", self._prompt_refs["planning.compose_answer"]
                ),
            },
        )
        merged = self._merge_decision(state, update, decision)
        merged.pop(PLANNING_AGENT_LOCAL_KEY, None)
        return cast(
            PlanningState,
            {**merged, "final_result": answer, "planning_disposition": "ANSWER"},
        )

    def _confirmation_patch(
        self, state: PlanningState, raw_confirmation: object
    ) -> dict[str, object]:
        if not self._is_production_integration:
            return {}
        if not isinstance(raw_confirmation, Mapping):
            raise ValueError("Planning confirmation must be an object")
        question = cast(str, raw_confirmation["question"])
        reason_codes = cast(list[str], raw_confirmation["reason_codes"])
        options = cast(list[str], raw_confirmation["options"])
        request_intent = cast(Mapping[str, object], state.get("request_intent", {}))
        clarification: ClarificationQuestionV1 = {
            "schema_version": 1,
            "origin_target": "planning.outline_answer",
            "question": question,
            "affected_field_paths": [],
            "reason_code": reason_codes[0],
            "known_context_summary": str(request_intent.get("goal", "Planning answer")),
            "options": [{"option_id": value, "label": value} for value in options],
        }
        assert self._id_factory is not None
        interrupt_id = self._id_factory()
        context = dict(cast(Mapping[str, object], state.get("prompt_context", {})))
        context.pop("confirmation_response", None)
        context["confirmation_interrupt"] = {
            "schema_version": 1,
            "interrupt_id": interrupt_id,
            "semantic_owner_id": "PLANNING",
            "origin_target": "planning.outline_answer",
        }
        return {
            "workflow_phase": WorkflowPhase.WAITING_CONFIRMATION.value,
            "user_interrupt": {
                **build_user_interrupt_v1(clarification),
                "interrupt_id": interrupt_id,
            },
            "prompt_context": context,
        }

    def _resolve_confirmation(self, state: PlanningState) -> PlanningState:
        if self._confirm_inline is None:
            raise RuntimeError("Planning confirmation controller is required")
        response, early = self._confirm_inline(cast(Mapping[str, object], state))
        if early is not None:
            return cast(
                PlanningState,
                {
                    **early,
                    "planning_confirmation": None,
                    "__planning_retry_outline__": False,
                    "final_result": {"disposition": "INTERRUPTED"},
                },
            )
        if response is None:
            raise ValueError("Planning confirmation response is required")
        context = dict(cast(Mapping[str, object], state.get("prompt_context", {})))
        context.pop("confirmation_interrupt", None)
        context["confirmation_response"] = dict(response)
        budget_decision = approve_planning_revision(state["retry_budget"])
        if budget_decision["decision"] != "ALLOW":
            raise ValueError("Planning confirmation revision budget is exhausted")
        return cast(
            PlanningState,
            {
                "planning_confirmation": None,
                "answer_outline": None,
                "user_interrupt": None,
                "prompt_context": context,
                "retry_budget": budget_decision["run_budget"],
                "__planning_retry_outline__": True,
            },
        )

    @property
    def _is_production_integration(self) -> bool:
        return (
            self._llm_runtime is not None
            and self._id_factory is not None
            and self._graph_profile is not None
            and self._merge_decision is not None
        )

    def _semantic_invoker(self, state: PlanningState) -> PlanningSemanticInvoker:
        if self._dependencies is not None:
            return self._dependencies.invoke
        if self._llm_runtime is None:
            raise RuntimeError("Planning semantic runtime dependency is required")
        llm_runtime = self._llm_runtime

        def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
            schemas: dict[str, OutputSchemaDefinition] = {
                "planning.outline_answer": ANSWER_OUTLINE_OUTPUT_SCHEMA,
                "planning.compose_answer": ANSWER_DRAFT_CANDIDATE_OUTPUT_SCHEMA,
            }
            prompt_ref = self._prompt_refs.get(prompt_id)
            output_schema = schemas.get(prompt_id)
            if prompt_ref is None or output_schema is None:
                raise ValueError(f"unsupported Planning Prompt slot: {prompt_id}")
            result = llm_runtime.invoke_structured(
                prompt_ref=prompt_ref,
                prompt_input=prompt_input,
                output_schema=output_schema,
                trace_context=self._llm_trace(state, prompt_id.rpartition(".")[2]),
            )
            if not isinstance(result.structured_output, Mapping):
                raise ValueError("Planning structured output must be an object")
            return result.structured_output

        return invoke

    def _project_runtime_inputs(self, state: PlanningState) -> PlanningState:
        working = cast(PlanningState, dict(state))
        if not isinstance(working.get("user_request"), str) and "__request__" in state:
            working["user_request"] = request_from_state(cast(Any, state)).request_text
        if "work_analysis" not in working and state.get("work_analysis_result") is not None:
            working["work_analysis"] = state["work_analysis_result"]
        if "evidence" not in working:
            working["evidence"] = self._evidence(state)
        context = state.get("prompt_context")
        if isinstance(context, Mapping) and isinstance(
            context.get("confirmation_response"), Mapping
        ):
            working["confirmation_response"] = dict(
                cast(Mapping[str, object], context["confirmation_response"])
            )
        return working

    def _evidence(self, state: PlanningState) -> list[EvidenceDraftV1]:
        direct = state.get("evidence")
        if isinstance(direct, list):
            return cast(list[EvidenceDraftV1], direct)
        retrieval = state.get("retrieval_result")
        if retrieval is None:
            return []
        if self._evidence_store is None:
            raise ValueError("Planning evidence_store is required for Retrieval evidence")
        return cast(
            list[EvidenceDraftV1],
            resolve_evidence_projection(
                store=self._evidence_store,
                run_id=cast(str, state["run_id"]),
                retrieval_result=cast(Any, retrieval),
            ),
        )

    def _materialize_answer(
        self, state: PlanningState, candidate: Mapping[str, object]
    ) -> dict[str, object]:
        assert self._id_factory is not None
        return {
            "schema_version": 2,
            "meta": {
                "artifact_id": self._id_factory(),
                "revision": 1,
                "based_on": self._based_on(state),
            },
            "answer": candidate["answer"],
            "evidence_refs": list(cast(list[str], candidate["evidence_refs"])),
        }

    @staticmethod
    def _based_on(state: PlanningState) -> list[StateArtifactRefV1]:
        result: list[StateArtifactRefV1] = []
        plan = state.get("tool_route_plan")
        output_plan = plan.get("output_plan") if isinstance(plan, Mapping) else None
        artifacts = (output_plan, state.get("work_analysis_result"), state.get("retrieval_result"))
        for artifact in artifacts:
            meta = artifact.get("meta") if isinstance(artifact, Mapping) else None
            if not isinstance(meta, Mapping):
                continue
            artifact_id, revision = meta.get("artifact_id"), meta.get("revision")
            if isinstance(artifact_id, str) and isinstance(revision, int):
                ref: StateArtifactRefV1 = {
                    "artifact_id": artifact_id,
                    "revision": revision,
                }
                if ref not in result:
                    result.append(ref)
        return result

    def _llm_trace(self, state: PlanningState, node: str) -> ObservabilityContext:
        request = request_from_state(cast(Any, state))
        return ObservabilityContext(
            request_id=request.correlation.request_id,
            command_id=request.correlation.command_id,
            conversation_id=request.conversation_id,
            run_id=request.run_id,
            langgraph_thread_id=request.workflow_key,
            llm_call_id=f"{request.run_id}:planning.{node}",
        )

    def _trace(
        self,
        state: PlanningState,
        node: str,
        prompt_ref: PromptReference,
        *,
        first: bool = False,
    ) -> dict[str, object]:
        assert self._graph_profile is not None
        assert self._id_factory is not None
        local = state.get(PLANNING_AGENT_LOCAL_KEY)
        invocation_id = (
            cast(str, local["invocation_id"]) if isinstance(local, Mapping) else self._id_factory()
        )
        return cast(
            dict[str, object],
            merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="planning",
                agent_role="planning",
                agent_invocation_id=invocation_id,
                subgraph_namespace="planning",
                node_name=node,
                llm_call_id=f"{state['run_id']}:planning.{node}",
                prompt_ref=prompt_ref,
                agent_invocation_increment=1 if first else 0,
                llm_call_increment=1,
            ),
        )


def _real_llm_results(
    route_results: tuple[RouteArgumentResult, ...],
) -> list[StructuredLLMResult]:
    return [
        route_result.llm_result
        for route_result in route_results
        if route_result.llm_result is not None
    ]


def _frozen_output_routes(
    state: Mapping[str, Any],
) -> tuple[OutputToolRouteV1, ...] | None:
    plan = state.get("tool_route_plan")
    return None if plan is None else output_routes(cast(Any, plan))


def _frozen_read_tool_ids(state: Mapping[str, Any]) -> frozenset[str]:
    plan = state.get("tool_route_plan")
    if not isinstance(plan, Mapping):
        return frozenset()
    input_plan = plan.get("input_plan")
    if not isinstance(input_plan, Mapping):
        return frozenset()
    routes = input_plan.get("input_routes")
    if not isinstance(routes, list):
        return frozenset()
    return frozenset(
        tool_id
        for route in routes
        if isinstance(route, Mapping)
        for tool_id in cast(list[str], route.get("allowed_read_tool_ids", []))
    )


__all__ = [
    "PlanningRuntimeDependencies",
    "PlanningSubgraph",
    "build_production_planning_runtime",
    "planning_answer_path_selected",
]
