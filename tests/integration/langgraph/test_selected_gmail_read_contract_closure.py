from __future__ import annotations

from itertools import count
from typing import cast

from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.adapters.langgraph.main.state import (
    WorkflowPhase,
    initial_graph_state,
)
from google_work_agent.adapters.langgraph.main.supervisor import (
    SupervisorTarget,
    route_supervisor,
)
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    execute_read_projection,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
)
from google_work_agent.application.agents.request_understanding.detect_ambiguity import (
    detect_ambiguity,
)
from google_work_agent.application.agents.request_understanding.finalize_intent import (
    finalize_intent,
)
from google_work_agent.application.agents.request_understanding.identify_goal import identify_goal
from google_work_agent.application.agents.retrieval.build_query import (
    RouteConstraintPolicy,
    build_query,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    RetrievalResultV1,
)
from google_work_agent.application.agents.retrieval.plan_query import plan_query
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    bind_registry_candidates,
)
from google_work_agent.application.agents.tool_routing.determine_io_resources import (
    determine_io_resources,
)
from google_work_agent.application.agents.tool_routing.finalize_route import finalize_route
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


def _prompt(prompt_id: str) -> PromptReference:
    owner, node = prompt_id.split(".", maxsplit=1)
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id=prompt_id,
        prompt_version="1",
        content_hash="hash",
        agent_role=owner,
        subgraph_name=owner,
        node_name=node,
        node_state="INITIAL",
        purpose=node,
        input_schema_version="v1",
        output_schema_version="v1",
    )


def test_selected_gmail_read__through_semantic_contracts__projects_exact_get() -> None:
    request = WorkflowStartRequest(
        run_id="run-selected",
        conversation_id="conversation-1",
        workflow_key="workflow-1",
        entry_mode="RESOURCE_SELECTED",
        requested_mode="LOCAL_GPU",
        request_text="선택한 메일을 읽고 요약해줘",
        selected_resource_ids=("thread-42",),
        selected_resources=(SelectedResourceRef("GMAIL", "THREAD", "thread-42"),),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
        run_budget=build_default_run_budget(),
    )
    goal_output: RequestGoalCandidateV1 = {
        "goal": "선택한 메일 읽기",
        "completion_conditions": ["선택한 메일을 요약한다"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "NONE",
    }
    runtime = FakeStructuredInferencePort(outputs=[goal_output])

    goal = identify_goal(
        llm_runtime=runtime,
        request=request,
        prompt_ref=_prompt("request_understanding.identify_goal"),
    )
    ambiguity = detect_ambiguity(
        llm_runtime=runtime,
        request=request,
        goal_candidate=goal,
        prompt_ref=_prompt("request_understanding.detect_ambiguity"),
    )
    intent = finalize_intent(goal, ambiguity, artifact_id="intent-1")
    catalog = load_signed_tool_registry()
    candidate, retry_budget = determine_io_resources(
        llm_runtime=runtime,
        tool_catalog=catalog,
        request_intent=intent,
        request=request,
        retry_budget=build_default_run_budget(),
        prompt_ref=_prompt("tool_routing.determine_io_resources"),
    )
    ids = count()
    binding = bind_registry_candidates(
        candidate=candidate,
        tool_catalog=catalog,
        id_factory=lambda: f"route-{next(ids)}",
    )
    route_result = finalize_route(
        request_intent=intent,
        binding=binding,
        selected_tools={},
        tool_catalog=catalog,
        id_factory=lambda: f"artifact-{next(ids)}",
    )
    route_plan = route_result["tool_route_plan"]
    assert route_plan is not None
    frozen_routes = route_plan["input_plan"]["input_routes"]
    plan, _, query_planning_llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=_prompt("retrieval.plan_query"),
        revision_prompt_ref=_prompt("retrieval.plan_query"),
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": intent, "input_routes": frozen_routes},
        requested_mode="LOCAL_GPU",
        frozen_routes=frozen_routes,
        route_policies={
            "route-0": RouteConstraintPolicy(frozenset({"RESOURCE_REF"}))
        },
        retry_budget=retry_budget,
        validated_resource_refs={"route-0": ["gmail_thread:thread-42"]},
    )
    fetch_plan = build_query(
        plan,
        frozen_routes=frozen_routes,
        route_policies={
            "route-0": RouteConstraintPolicy(frozenset({"RESOURCE_REF"}))
        },
        validated_resource_refs={"route-0": ["gmail_thread:thread-42"]},
    )[0]
    tool_id, arguments = execute_read_projection.project_connector_call(
        fetch_plan,
        route=frozen_routes[0],
        page_size=20,
        detail_resource=cast(
            dict[str, object],
            {"resource_type": "gmail_thread", "resource_id": "thread-42", "parent_id": None},
        ),
    )

    assert ambiguity == {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
    assert candidate.output_mode == "ANSWER"
    assert [route["resource_type"] for route in frozen_routes] == ["GMAIL_THREAD"]
    assert query_planning_llm_invoked is False
    assert plan["route_queries"][0]["operation"] == "DETAIL_FETCH"
    assert tool_id == "gmail_get_thread"
    assert arguments == {"thread_id": "thread-42"}
    assert [
        cast(PromptReference, call["prompt_ref"]).prompt_id for call in runtime.calls
    ] == [
        "request_understanding.identify_goal",
    ]

    state = initial_graph_state(
        request,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        graph_version="selected-gmail-contract-test",
        initial_target="request_understanding",
    )
    state["request_intent"] = intent
    route_decision = route_supervisor(
        phase=WorkflowPhase.TOOL_ROUTING,
        state=state,
        result=route_result,
    )
    assert route_decision["target"] == SupervisorTarget.CONTEXT_RETRIEVAL.value
    state.update(route_decision["state_update"])
    retrieval_decision = route_supervisor(
        phase=WorkflowPhase.CONTEXT_RETRIEVAL,
        state=state,
        result={
            "disposition": "SUFFICIENT",
            "typed_result": cast(
                RetrievalResultV1,
                {
                    "schema_version": 1,
                    "meta": {
                        "artifact_id": "retrieval-1",
                        "revision": 1,
                        "based_on": [],
                    },
                    "evidence_refs": [],
                },
            ),
        },
    )
    assert retrieval_decision["target"] == SupervisorTarget.SOLUTION_PLANNING.value
