"""Canonical six-node Planning production graph."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

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
    ProductionGraphStateV2,
    request_from_state,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraph_state import (
    PlanningInputState,
    PlanningLocalState,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes import (
    assemble_plan_node as assemble_node_module,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes import (
    build_dependencies_node as dependencies_node_module,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes import (
    compose_arguments_per_output_route_node as arguments_node_module,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes import (
    draft_action_objective_per_output_route_node as objective_node_module,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.compose_answer_node import (
    compose_answer_node,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.outline_answer_node import (
    outline_answer_node,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.routing import (
    route_after_assemble_plan as assemble_routing,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.routing import (
    route_after_build_dependencies as dependencies_routing,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.routing import (
    route_after_compose_answer as compose_answer_routing,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.routing import (
    route_after_compose_arguments_per_output_route as arguments_routing,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.routing import (
    route_after_draft_action_objective_per_output_route as objective_routing,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.routing import (
    route_after_outline_answer as outline_answer_routing,
)
from google_work_agent.application.agents.planning.assemble_plan import materialize_action_seeds
from google_work_agent.application.agents.planning.choose_answer_or_action_from_route import (
    choose_answer_or_action_from_route,
)
from google_work_agent.application.agents.planning.compose_answer import (
    ANSWER_DRAFT_CANDIDATE_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.planning.compose_arguments_per_output_route import (
    TOOL_ARGUMENT_CANDIDATE_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.planning.draft_action_objective_per_output_route import (
    ACTION_OBJECTIVE_CANDIDATE_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.planning.outline_answer import (
    ANSWER_OUTLINE_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.planning.resolve_default_container import (
    RequiredContainerUnresolvedError,
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
from google_work_agent.application.orchestration.retrieval_evidence_store import (
    RunScopedEvidenceStore,
    resolve_evidence_projection,
)
from google_work_agent.application.orchestration.supervisor import (
    SupervisorDecisionV1,
    SupervisorTarget,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.llm import OutputSchemaDefinition, PromptReference
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


class PlanningSubgraph:
    """Execute the exact ANSWER or ACTION path selected by frozen Tool Route."""

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
        default_tasklist_id_provider: Callable[[], str | None] | None = None,
        default_calendar_id_provider: Callable[[], str | None] | None = None,
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
        self._default_tasklist_id_provider = default_tasklist_id_provider
        self._default_calendar_id_provider = default_calendar_id_provider
        self._prompt_refs: dict[str, PromptReference] = {}
        self._prompt_manifest_path = prompt_manifest_path or default_prompt_manifest_path()
        if llm_runtime is not None:
            self._prompt_refs = {
                "planning.outline_answer": load_prompt_reference(
                    "planning.outline_answer", self._prompt_manifest_path
                ),
                "planning.compose_answer": load_prompt_reference(
                    "planning.compose_answer", self._prompt_manifest_path
                ),
            }

    def build(self) -> Any:
        graph = (
            StateGraph(
                PlanningLocalState,
                input_schema=PlanningInputState,
                output_schema=ProductionGraphStateV2,
            )
            if self._is_production_integration
            else StateGraph(PlanningLocalState)
        )
        graph.add_node("outline_answer", self._outline_answer_node)
        graph.add_node("compose_answer", self._compose_answer_node)
        graph.add_node("draft_action_objective_per_output_route", self._draft_action_objective_node)
        graph.add_node("compose_arguments_per_output_route", self._compose_arguments_node)
        graph.add_node("derive_dependencies", self._derive_dependencies_node)
        graph.add_node("assemble", self._assemble_node)
        graph.add_conditional_edges(
            START,
            self._route_at_entry,
            {
                "outline_answer": "outline_answer",
                "draft_action_objective_per_output_route": (
                    "draft_action_objective_per_output_route"
                ),
            },
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
        graph.add_conditional_edges(
            "draft_action_objective_per_output_route",
            objective_routing.route_after_draft_action_objective_per_output_route,
            {
                "compose_arguments_per_output_route": "compose_arguments_per_output_route",
                "end": END,
            },
        )
        graph.add_conditional_edges(
            "compose_arguments_per_output_route",
            arguments_routing.route_after_compose_arguments_per_output_route,
            {"derive_dependencies": "derive_dependencies", "end": END},
        )
        graph.add_conditional_edges(
            "derive_dependencies",
            dependencies_routing.route_after_build_dependencies,
            {"assemble": "assemble"},
        )
        graph.add_conditional_edges(
            "assemble",
            assemble_routing.route_after_assemble_plan,
            {"end": END},
        )
        return graph.compile(name="planning_subgraph")

    @staticmethod
    def _route_at_entry(state: PlanningLocalState) -> str:
        return (
            "outline_answer"
            if planning_answer_path_selected(cast(Mapping[str, object], state))
            else "draft_action_objective_per_output_route"
        )

    def _outline_answer_node(self, state: PlanningLocalState) -> PlanningLocalState:
        working = self._project_runtime_inputs(state)
        if self._llm_runtime is not None:
            ensure_llm_call_budget(cast(Any, working))
        patch = outline_answer_node(
            cast(Mapping[str, object], working),
            invoke=self._semantic_invoker(state),
        )
        result = cast(
            PlanningLocalState,
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
            trace_state = cast(PlanningLocalState, {**state, **result})
            result["retry_budget"] = consume_llm_call_budget(cast(Any, state))
            result["trace_context"] = self._trace(
                trace_state,
                "outline_answer",
                self._prompt_refs["planning.outline_answer"],
                first=not isinstance(state.get(PLANNING_AGENT_LOCAL_KEY), Mapping),
            )
        return result

    def _compose_answer_node(self, state: PlanningLocalState) -> PlanningLocalState:
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
                PlanningLocalState,
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
            PlanningLocalState,
            {**merged, "final_result": answer, "planning_disposition": "ANSWER"},
        )

    def _draft_action_objective_node(self, state: PlanningLocalState) -> PlanningLocalState:
        interrupt = state.get("user_interrupt")
        if isinstance(interrupt, Mapping) and interrupt.get("origin_target") == (
            "planning.compose_arguments_per_output_route"
        ):
            state = self._resolve_action_confirmation(state)
            if isinstance(state.get("final_result"), Mapping):
                return state
        working = self._project_runtime_inputs(state)
        routes = cast(Mapping[str, object], working["output_plan"])["output_routes"]
        if self._llm_runtime is not None:
            ensure_llm_call_budget(
                cast(Any, working), provider_calls_requested=len(cast(list[object], routes))
            )
        patch = objective_node_module.draft_action_objective_per_output_route_node(
            cast(Mapping[str, object], working),
            invoke=self._semantic_invoker(state),
        )
        result = cast(
            PlanningLocalState,
            {
                **patch,
                "user_request": working["user_request"],
                "request_intent": working["request_intent"],
                "output_plan": working["output_plan"],
                "evidence": working.get("evidence", []),
                "evidence_refs": working.get("evidence_refs", []),
                "user_interrupt": state.get("user_interrupt"),
                "prompt_context": state.get("prompt_context", {}),
                "planning_disposition": "ACTION",
            },
        )
        if "work_analysis" in working:
            result["work_analysis"] = working["work_analysis"]
        if self._llm_runtime is not None:
            result["retry_budget"] = consume_llm_call_budget(
                cast(Any, state), provider_calls_consumed=len(cast(list[object], routes))
            )
            result["trace_context"] = self._trace(
                state,
                "draft_action_objective_per_output_route",
                self._prompt_refs["planning.draft_action_objective_per_output_route"],
                first=not isinstance(state.get(PLANNING_AGENT_LOCAL_KEY), Mapping),
            )
        return result

    def _compose_arguments_node(self, state: PlanningLocalState) -> PlanningLocalState:
        working = self._project_runtime_inputs(state)
        routes = cast(Mapping[str, object], working["output_plan"])["output_routes"]
        if self._llm_runtime is not None:
            ensure_llm_call_budget(
                cast(Any, working), provider_calls_requested=len(cast(list[object], routes))
            )
        try:
            patch = arguments_node_module.compose_arguments_per_output_route_node(
                cast(Mapping[str, object], working),
                invoke=self._semantic_invoker(state),
                default_tasklist_id_provider=self._default_tasklist_id_provider,
                default_calendar_id_provider=self._default_calendar_id_provider,
            )
        except RequiredContainerUnresolvedError as exc:
            confirmation = {
                "disposition": "NEEDS_CONFIRMATION",
                "question": (
                    f"Provide the required {exc.argument_name} for "
                    f"the selected {exc.tool_id} action."
                ),
                "options": [],
                "reason_codes": ["REQUIRED_CONTAINER_UNRESOLVED"],
            }
            interrupt_patch = self._confirmation_patch(
                state,
                confirmation,
                origin_target="planning.compose_arguments_per_output_route",
            )
            context = dict(cast(Mapping[str, object], interrupt_patch.get("prompt_context", {})))
            context["planning_missing_container"] = {
                "route_id": exc.route_id,
                "tool_id": exc.tool_id,
                "argument_name": exc.argument_name,
            }
            return cast(
                PlanningLocalState,
                {
                    **interrupt_patch,
                    "prompt_context": context,
                    "planning_confirmation": confirmation,
                    "final_result": {"disposition": "NEEDS_CONFIRMATION"},
                },
            )
        seeds = materialize_action_seeds(
            output_routes=cast(Any, routes),
            argument_candidates=cast(Any, patch["argument_candidates"]),
            action_id_factory=self._id_factory or (lambda: str(uuid4())),
        )
        result = cast(
            PlanningLocalState,
            {**patch, "__planning_action_seeds__": list(seeds)},
        )
        context = dict(cast(Mapping[str, object], state.get("prompt_context", {})))
        context.pop("confirmation_response", None)
        context.pop("confirmation_interrupt", None)
        context.pop("planning_missing_container", None)
        result["prompt_context"] = context
        if self._llm_runtime is not None:
            result["retry_budget"] = consume_llm_call_budget(
                cast(Any, state), provider_calls_consumed=len(cast(list[object], routes))
            )
            result["trace_context"] = self._trace(
                state,
                "compose_arguments_per_output_route",
                self._prompt_refs["planning.compose_arguments_per_output_route"],
            )
        return result

    @staticmethod
    def _derive_dependencies_node(state: PlanningLocalState) -> PlanningLocalState:
        return cast(
            PlanningLocalState,
            dependencies_node_module.build_dependencies_node(cast(Mapping[str, object], state)),
        )

    def _assemble_node(self, state: PlanningLocalState) -> PlanningLocalState:
        patch = assemble_node_module.assemble_plan_node(
            cast(Mapping[str, object], state),
            artifact_id_factory=self._id_factory or (lambda: str(uuid4())),
            based_on=[dict(ref) for ref in self._based_on(state)],
        )
        plan = cast(dict[str, object], patch["final_result"])
        if not self._is_production_integration:
            return cast(
                PlanningLocalState,
                {**patch, "planning_result": plan, "planning_disposition": "ACTION"},
            )
        assert self._merge_decision is not None
        decision: SupervisorDecisionV1 = {
            "target": SupervisorTarget.PLAN_REVIEW_INSPECT.value,
            "next_phase": WorkflowPhase.PLAN_REVIEW.value,
            "state_update": cast(
                GraphStateUpdateV1,
                {
                    "workflow_phase": WorkflowPhase.PLAN_REVIEW.value,
                    "planning_result": plan,
                    "workflow_signal": None,
                    "user_interrupt": None,
                    "finalize_intent": None,
                },
            ),
            "reason_code": "PLAN_READY",
            "budget_decision": None,
        }
        merged = self._merge_decision(
            state,
            cast(GraphStateUpdateV1, {"planning_result": plan}),
            decision,
        )
        merged.pop(PLANNING_AGENT_LOCAL_KEY, None)
        return cast(PlanningLocalState, {**merged, "final_result": plan})

    def _confirmation_patch(
        self,
        state: PlanningLocalState,
        raw_confirmation: object,
        *,
        origin_target: str = "planning.outline_answer",
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
            "origin_target": origin_target,
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
            "origin_target": origin_target,
        }
        return {
            "workflow_phase": WorkflowPhase.WAITING_CONFIRMATION.value,
            "user_interrupt": {
                **build_user_interrupt_v1(clarification),
                "interrupt_id": interrupt_id,
            },
            "prompt_context": context,
        }

    def _resolve_action_confirmation(self, state: PlanningLocalState) -> PlanningLocalState:
        if self._confirm_inline is None:
            raise RuntimeError("Planning confirmation controller is required")
        response, early = self._confirm_inline(cast(Mapping[str, object], state))
        if early is not None:
            return cast(
                PlanningLocalState,
                {**early, "final_result": {"disposition": "INTERRUPTED"}},
            )
        if response is None:
            raise ValueError("Planning container confirmation response is required")
        context = dict(cast(Mapping[str, object], state.get("prompt_context", {})))
        context.pop("confirmation_interrupt", None)
        context["confirmation_response"] = dict(response)
        return cast(
            PlanningLocalState,
            {
                **state,
                "user_interrupt": None,
                "planning_confirmation": None,
                "prompt_context": context,
            },
        )

    def _resolve_confirmation(self, state: PlanningLocalState) -> PlanningLocalState:
        if self._confirm_inline is None:
            raise RuntimeError("Planning confirmation controller is required")
        response, early = self._confirm_inline(cast(Mapping[str, object], state))
        if early is not None:
            return cast(
                PlanningLocalState,
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
            PlanningLocalState,
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

    def _semantic_invoker(self, state: PlanningLocalState) -> PlanningSemanticInvoker:
        if self._dependencies is not None:
            return self._dependencies.invoke
        if self._llm_runtime is None:
            raise RuntimeError("Planning semantic runtime dependency is required")
        llm_runtime = self._llm_runtime

        def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
            schemas: dict[str, OutputSchemaDefinition] = {
                "planning.outline_answer": ANSWER_OUTLINE_OUTPUT_SCHEMA,
                "planning.compose_answer": ANSWER_DRAFT_CANDIDATE_OUTPUT_SCHEMA,
                "planning.draft_action_objective_per_output_route": (
                    ACTION_OBJECTIVE_CANDIDATE_OUTPUT_SCHEMA
                ),
                "planning.compose_arguments_per_output_route": (
                    TOOL_ARGUMENT_CANDIDATE_OUTPUT_SCHEMA
                ),
            }
            prompt_ref = self._prompt_refs.get(prompt_id)
            if prompt_ref is None and prompt_id in {
                "planning.draft_action_objective_per_output_route",
                "planning.compose_arguments_per_output_route",
            }:
                prompt_ref = load_prompt_reference(prompt_id, self._prompt_manifest_path)
                self._prompt_refs[prompt_id] = prompt_ref
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

    def _project_runtime_inputs(self, state: PlanningLocalState) -> PlanningLocalState:
        working = cast(PlanningLocalState, dict(state))
        if not isinstance(working.get("user_request"), str) and "__request__" in state:
            working["user_request"] = request_from_state(cast(Any, state)).request_text
        if "work_analysis" not in working and state.get("work_analysis_result") is not None:
            working["work_analysis"] = cast(Any, state["work_analysis_result"])
        plan = state.get("tool_route_plan")
        if "output_plan" not in working and isinstance(plan, Mapping):
            output_plan = plan.get("output_plan")
            if isinstance(output_plan, Mapping):
                working["output_plan"] = dict(output_plan)
        if "evidence" not in working:
            working["evidence"] = self._evidence(state)
        working["evidence_refs"] = [
            ref
            for item in cast(list[Mapping[str, object]], working.get("evidence", []))
            for ref in (item.get("evidence_ref") or item.get("evidence_id") or item.get("id"),)
            if isinstance(ref, str) and ref
        ]
        context = state.get("prompt_context")
        if isinstance(context, Mapping) and isinstance(
            context.get("confirmation_response"), Mapping
        ):
            working["confirmation_response"] = dict(
                cast(Mapping[str, object], context["confirmation_response"])
            )
        return working

    def _evidence(self, state: PlanningLocalState) -> list[EvidenceDraftV1]:
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
        self, state: PlanningLocalState, candidate: Mapping[str, object]
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
    def _based_on(state: PlanningLocalState) -> list[StateArtifactRefV1]:
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

    def _llm_trace(self, state: PlanningLocalState, node: str) -> ObservabilityContext:
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
        state: PlanningLocalState,
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


__all__ = [
    "PlanningRuntimeDependencies",
    "PlanningSubgraph",
    "planning_answer_path_selected",
]
