from __future__ import annotations

from collections.abc import Callable, Mapping
from itertools import count
from typing import Any, cast

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    WorkflowPhase,
    initial_graph_state,
)
from google_work_agent.adapters.langgraph.main.supervisor import route_supervisor
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.planning.graph import (
    PlanningRuntimeDependencies,
    PlanningSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.routing import (
    route_after_assemble_plan as planning_assemble_routing,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.graph import (
    RequestUnderstandingSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.routing import (
    route_after_finalize_intent as request_finalize_routing,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.graph import RetrievalSubgraph
from google_work_agent.adapters.langgraph.subgraphs.review.graph import (
    ReviewRuntimeDependencies,
    ReviewSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.review.routing.route_after_entry import (
    route_after_entry,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.graph import ToolRoutingSubgraph
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.routing import (
    route_after_validate_route as tool_validation_routing,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.graph import WorkAnalysisSubgraph
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.routing import (
    route_after_assess_information_gaps as work_gap_routing,
)
from google_work_agent.adapters.system.memory.retrieval_evidence_store import (
    RunScopedEvidenceStore,
)
from google_work_agent.adapters.system.memory.run_retrieval_cache import (
    InMemoryRunRetrievalCache,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewSemanticInvoker,
)
from google_work_agent.application.prompt_runtime.prompt_registry import DEVELOPMENT_SMOKE
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


class _IdFactory:
    def __init__(self) -> None:
        self._values = count()

    def __call__(self) -> str:
        return f"component-id-{next(self._values)}"


class _ComponentInferencePort:
    def __init__(self, *, request_confirmation: bool = False) -> None:
        self.request_confirmation = request_confirmation
        self.calls: list[str] = []

    def infer(
        self,
        requested_mode: str,
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        del requested_mode, output_schema_ref
        prompt_id = prompt_ref.prompt_id
        self.calls.append(prompt_id)
        base = input_projection.get("base_projection", input_projection)
        projection = cast(Mapping[str, object], base)
        output = self._response(prompt_id, projection)
        return StructuredInferenceResultV1(
            schema_version=1,
            structured_output=output,
            provider="component-fake",
            model="component-fake",
            actual_runtime="API_LLM",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            fallback_reason=None,
        )

    def _response(
        self, prompt_id: str, projection: Mapping[str, object]
    ) -> dict[str, object]:
        has_confirmation = isinstance(projection.get("confirmation_response"), Mapping)
        if prompt_id == "request_understanding.identify_goal":
            return {
                "goal": "schedule team sync" if has_confirmation else "summarize status",
                "completion_conditions": ["return a result"],
                "constraints": [],
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": [],
                "analysis_requirement": "NONE",
            }
        if prompt_id == "request_understanding.detect_ambiguity":
            needs_confirmation = self.request_confirmation and not has_confirmation
            return {
                "requires_confirmation": needs_confirmation,
                "reason_codes": ["MISSING_TARGET"] if needs_confirmation else [],
                "missing_fields": ["target"] if needs_confirmation else [],
            }
        if prompt_id == "tool_routing.determine_io_resources":
            return {
                "schema_version": 1,
                "input_resource_types": [],
                "output_resource_types": [],
                "output_effects": [],
                "disposition": "NO_TOOL_NEEDED",
            }
        if prompt_id == "retrieval.plan_query":
            return {
                "schema_version": 2,
                "route_queries": [
                    {
                        "route_id": "route-1",
                        "operation": "SEARCH",
                        "reason_codes": ["USER_REQUEST"],
                        "search_spec": {
                            "mode": "INITIAL",
                            "constraints": [
                                {
                                    "kind": "KEYWORD",
                                    "terms": ["status"],
                                    "match_mode": "ANY",
                                }
                            ],
                        },
                        "detail_candidate_ref": None,
                    }
                ],
                "required_information": ["status"],
                "retrieval_order": ["route-1"],
            }
        if prompt_id == "retrieval.select_evidence":
            ranked = cast(list[Mapping[str, object]], projection.get("ranked_segments", []))
            segment_ids = [str(item["segment_id"]) for item in ranked]
            return {
                "schema_version": 2,
                "evidence_drafts": [
                    {
                        "segment_id": segment_id,
                        "role": "SUPPORTS",
                        "relevance_reason": "status evidence",
                    }
                    for segment_id in segment_ids
                ],
                "selected_segment_ids": segment_ids,
                "excluded_segment_ids": [],
            }
        if prompt_id == "retrieval.assess_sufficiency":
            return {"schema_version": 2, "status": "SUFFICIENT", "issues": []}
        if prompt_id == "work_analysis.extract_work_facts":
            return {"fact_candidates": []}
        if prompt_id == "work_analysis.assess_information_gaps":
            return {
                "disposition": "COMPLETE",
                "ambiguities": [],
                "retrieval_needs": [],
                "evidence_refs": [],
            }
        if prompt_id == "work_analysis.assess_operational_risks":
            return {
                "risks": [],
                "action_necessity_candidate": "NOT_REQUIRED",
                "action_necessity_reason": "Answer only",
                "evidence_refs": [],
            }
        raise AssertionError(f"unexpected component Prompt: {prompt_id}")


class _ComponentConnectorReadPort:
    def __init__(self) -> None:
        self.call_count = 0

    def execute_read(
        self, binding: Any, tool_arguments: dict[str, Any]
    ) -> ConnectorReadResultV1:
        del tool_arguments
        self.call_count += 1
        return ConnectorReadResultV1(
            schema_version=1,
            tool_id=binding.tool_id,
            request_id="component-read-1",
            output={
                "items": [
                    {
                        "resource_type": "gmail_thread",
                        "resource_id": "thread-1",
                        "parent_id": None,
                        "version": "v1",
                        "related_resource_ids": [],
                        "payload": {"subject": "Weekly status"},
                    }
                ]
            },
            next_page_token=None,
            total_count=1,
        )


def _state(*, initial_target: str = "request_understanding") -> GraphState:
    request = WorkflowStartRequest(
        run_id="component-run-1",
        conversation_id="component-conversation-1",
        workflow_key="component-thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="summarize status",
        selected_resource_ids=(),
        run_budget=build_default_run_budget(),
        correlation=WorkflowCorrelationContext("component-request-1", None, "1"),
    )
    return initial_graph_state(
        request,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        graph_version="component-test",
        initial_target=initial_target,
    )


def _intent() -> dict[str, object]:
    return {
        "schema_version": 2,
        "goal": "summarize status",
        "completion_conditions": ["return a result"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": [],
        "analysis_requirement": "NONE",
        "ambiguity": {
            "requires_confirmation": False,
            "reason_codes": [],
            "missing_fields": [],
        },
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
    }


def _answer_route_plan(*, with_input_route: bool = False) -> dict[str, object]:
    input_routes: list[dict[str, object]] = []
    if with_input_route:
        input_routes.append(
            {
                "route_id": "route-1",
                "resource_type": "EMAIL",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["gmail_search_threads"],
                "required": True,
                "reason_codes": ["USER_REQUEST"],
            }
        )
    based_on = [{"artifact_id": "intent-1", "revision": 1}]
    return {
        "schema_version": 2,
        "input_plan": {
            "schema_version": 1,
            "meta": {"artifact_id": "input-1", "revision": 1, "based_on": based_on},
            "input_routes": input_routes,
        },
        "output_plan": {
            "schema_version": 1,
            "meta": {"artifact_id": "output-1", "revision": 1, "based_on": based_on},
            "output_mode": "ANSWER",
        },
        "tool_registry_version": "component-test",
    }


def _retrieval_result() -> dict[str, object]:
    return {
        "schema_version": 1,
        "meta": {
            "artifact_id": "retrieval-1",
            "revision": 1,
            "based_on": [{"artifact_id": "intent-1", "revision": 1}],
        },
        "coverage": "NO_FETCH_NEEDED",
        "context_bundle_ref": None,
        "evidence_refs": [],
        "selected_segment_ids": [],
        "excluded_segment_ids": [],
        "source_resource_refs": [],
        "source_statuses": [],
        "availability_results": [],
        "missing_information": [],
        "retrieval_rounds": 0,
    }


def _merge_decision(
    state: Mapping[str, object], update: Mapping[str, object], decision: Mapping[str, object]
) -> dict[str, object]:
    decision_state = cast(Mapping[str, object], decision["state_update"])
    return {
        **state,
        **update,
        **decision_state,
        "__target__": cast(str, decision["target"]),
    }


def _confirm_early(_state: object) -> tuple[None, dict[str, object]]:
    return None, {"__target__": "end", "__workflow_control__": {"stage": "PAUSED"}}


def _edge_set(graph: Any) -> set[tuple[str, str]]:
    return {(edge.source, edge.target) for edge in graph.get_graph().edges}


def test_request_understanding__compiled_normal_path__produces_intent() -> None:
    llm = _ComponentInferencePort()
    graph = RequestUnderstandingSubgraph(
        llm_runtime=llm,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision),
        confirm_inline=_confirm_early,
    ).build()

    with provider_dispatch_execution_scope():
        result = graph.invoke(_state())

    assert result["request_intent"]["goal"] == "summarize status"
    assert llm.calls == [
        "request_understanding.identify_goal",
        "request_understanding.detect_ambiguity",
    ]
    assert ("finalize_intent", "identify_goal") in _edge_set(graph)


def test_tool_routing__compiled_normal_path__produces_answer_route() -> None:
    state = _state(initial_target="tool_route")
    state["request_intent"] = cast(Any, _intent())
    llm = _ComponentInferencePort()
    graph = ToolRoutingSubgraph(
        llm_runtime=llm,
        tool_catalog=load_development_tool_registry(),
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        merge_decision=cast(Any, _merge_decision),
        confirm_inline=cast(Any, _confirm_early),
        id_factory=_IdFactory(),
    ).build()

    with provider_dispatch_execution_scope():
        result = graph.invoke(state)

    assert result["tool_route_plan"]["output_plan"]["output_mode"] == "ANSWER"
    assert llm.calls == ["tool_routing.determine_io_resources"]
    assert ("finalize_route", "determine_io_resources") in _edge_set(graph)


def test_retrieval__compiled_normal_path__materializes_evidence() -> None:
    state = _state(initial_target="context_retriever")
    state["request_intent"] = cast(Any, _intent())
    state["tool_route_plan"] = cast(Any, _answer_route_plan(with_input_route=True))
    llm = _ComponentInferencePort()
    connector = _ComponentConnectorReadPort()
    graph = RetrievalSubgraph(
        llm_runtime=llm,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision),
        evidence_store=RunScopedEvidenceStore(),
        connector_reader=connector,
        tool_catalog=load_development_tool_registry(),
        read_result_cache=InMemoryRunRetrievalCache(),
        confirm_inline=cast(Any, _confirm_early),
    ).build()

    with provider_dispatch_execution_scope():
        result = graph.invoke(state)

    assert result["retrieval_result"]["coverage"] == "SUFFICIENT"
    assert result["retrieval_result"]["evidence_refs"]
    assert connector.call_count == 1
    assert ("assess_sufficiency", "plan_query") in _edge_set(graph)
    assert ("finalize", "finalize") in _edge_set(graph)


def test_work_analysis__compiled_normal_path__produces_analysis() -> None:
    state = _state(initial_target="work_analysis")
    state["request_intent"] = cast(Any, _intent())
    state["tool_route_plan"] = cast(Any, _answer_route_plan())
    state["retrieval_result"] = cast(Any, _retrieval_result())
    llm = _ComponentInferencePort()
    graph = WorkAnalysisSubgraph(
        llm_runtime=llm,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision),
        evidence_store=RunScopedEvidenceStore(),
        confirm_inline=cast(Any, _confirm_early),
    ).build()

    with provider_dispatch_execution_scope():
        result = graph.invoke(state)

    assert result["work_analysis_result"]["schema_version"] == 2
    assert result["__target__"] == "SOLUTION_PLANNING"
    assert ("finalize", "assess_operational_risks") in _edge_set(graph)


def test_planning__compiled_normal_path__produces_answer() -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        if prompt_id == "planning.outline_answer":
            return {"sections": ["summary"], "evidence_refs": []}
        return {"schema_version": 2, "answer": "done", "evidence_refs": []}

    graph = PlanningSubgraph(
        dependencies=PlanningRuntimeDependencies(
            invoke=cast(PlanningSemanticInvoker, invoke)
        )
    ).build()
    result = graph.invoke(
        {
            "user_request": "summarize status",
            "request_intent": _intent(),
            "tool_route_plan": _answer_route_plan(),
            "work_analysis": {},
            "evidence": [],
        }
    )

    assert result["planning_disposition"] == "ANSWER"
    assert calls == ["planning.outline_answer", "planning.compose_answer"]
    assert ("compose_answer", "outline_answer") in _edge_set(graph)


def test_review__compiled_normal_path__passes_review() -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        return {"schema_version": 1, "dimension": prompt_id, "findings": []}

    graph = ReviewSubgraph(
        dependencies=ReviewRuntimeDependencies(invoke=cast(ReviewSemanticInvoker, invoke))
    ).build()
    result = graph.invoke(
        {
            "review_phase": "INITIAL",
            "request_intent": _intent(),
            "tool_route_plan": _answer_route_plan(),
            "planning_result": {"answer": "done"},
            "work_analysis": {},
            "evidence": [],
            "policy_summary": {},
            "review_artifact_id": "review-1",
            "review_revision": 1,
            "review_based_on": [],
        }
    )

    assert result["review_result"]["status"] == "PASS"
    assert calls == ["review.inspect_goal_and_evidence"]
    assert ("recheck", "aggregate_findings") in _edge_set(graph)


def test_request_confirmation__interrupts_and_resumes__same_owner() -> None:
    llm = _ComponentInferencePort(request_confirmation=True)

    def confirm_inline(
        state: Mapping[str, object],
    ) -> tuple[ConfirmationResponseProjectionV1, None]:
        user_interrupt = cast(Mapping[str, object], state["user_interrupt"])
        resume = interrupt(
            {
                "semantic_owner_id": "REQUEST_UNDERSTANDING",
                "origin_target": user_interrupt["origin_target"],
            }
        )
        return cast(ConfirmationResponseProjectionV1, resume["confirmation_response"]), None

    request_graph = RequestUnderstandingSubgraph(
        llm_runtime=llm,
        prompt_manifest_path=None,
        prompt_execution_scope=DEVELOPMENT_SMOKE,
        id_factory=_IdFactory(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        transition_run=lambda _run_id, _transition: None,
        merge_decision=cast(Any, _merge_decision),
        confirm_inline=confirm_inline,
    ).build()
    wrapper = StateGraph(GraphState)
    wrapper.add_node("request_understanding", request_graph)
    wrapper.add_edge(START, "request_understanding")
    wrapper.add_edge("request_understanding", END)
    graph = wrapper.compile(checkpointer=InMemorySaver())
    config: RunnableConfig = {
        "configurable": {"thread_id": "component-confirmation-thread"}
    }

    with provider_dispatch_execution_scope():
        interrupted = graph.invoke(_state(), config)

    assert interrupted["__interrupt__"][0].value == {
        "semantic_owner_id": "REQUEST_UNDERSTANDING",
        "origin_target": "request.detect_ambiguity",
    }
    assert graph.get_state(config).next == ("request_understanding",)

    with provider_dispatch_execution_scope():
        resumed = graph.invoke(
            Command(
                resume={
                    "confirmation_response": {
                        "schema_version": 1,
                        "response_kind": "FREE_TEXT",
                        "selected_option": None,
                        "free_text": "team sync tomorrow",
                    }
                }
            ),
            config,
        )

    assert resumed["request_intent"]["goal"] == "schedule team sync"
    assert graph.get_state(config).next == ()
    assert llm.calls.count("request_understanding.identify_goal") == 2


@pytest.mark.parametrize(
    ("router", "state"),
    [
        (request_finalize_routing.route_after_finalize_intent, {}),
        (tool_validation_routing.route_after_validate_route, {}),
        (work_gap_routing.route_after_assess_information_gaps, {}),
        (planning_assemble_routing.route_after_assemble_plan, {}),
        (route_after_entry, {"review_phase": "UNKNOWN"}),
    ],
)
def test_agent_router__unknown_disposition__raises(
    router: Callable[[Any], str], state: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        router(state)


@pytest.mark.parametrize(
    ("phase", "result"),
    [
        (WorkflowPhase.REQUEST_ANALYSIS, {"result": "UNKNOWN"}),
        (WorkflowPhase.PLAN_REVIEW, {"status": "UNKNOWN"}),
    ],
)
def test_supervisor__unknown_agent_disposition__raises(
    phase: WorkflowPhase, result: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        route_supervisor(phase=phase, state=_state(), result=result)


def test_supervisor__unknown_tool_disposition__routes_recovery() -> None:
    decision = route_supervisor(
        phase=WorkflowPhase.TOOL_ROUTING,
        state=_state(),
        result={"disposition": "UNKNOWN"},
    )

    assert decision["target"] == "RECOVERY"
    assert decision["reason_code"] == "TOOL_ROUTE_CONTRACT_VIOLATION"


def test_supervisor__unknown_retrieval_disposition__blocks_instead_of_normal_route() -> None:
    decision = route_supervisor(
        phase=WorkflowPhase.CONTEXT_RETRIEVAL,
        state=_state(),
        result={"disposition": "UNKNOWN", "typed_result": None},
    )

    assert decision["target"] == "FINALIZE"
    finalize_intent = decision["state_update"]["finalize_intent"]
    assert finalize_intent is not None
    assert finalize_intent["intent"] == "BLOCKED"
    assert finalize_intent["reason_code"] == "CONTEXT_BLOCKED"
