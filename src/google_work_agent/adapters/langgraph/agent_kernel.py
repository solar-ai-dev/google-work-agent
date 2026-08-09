"""Shared helpers for native LangGraph agent subgraphs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.application.workflows import AgentLocalStateV1, PromptRef
from google_work_agent.ports import PromptReference, StructuredLLMResult

GraphState = Mapping[str, object]


def build_agent_local_state(
    *,
    agent_role: str,
    invocation_id: str,
    node_state: str,
    input_projection: dict[str, object],
    prompt_ref: PromptReference | None = None,
) -> AgentLocalStateV1:
    return {
        "schema_version": 1,
        "agent_role": agent_role,
        "invocation_id": invocation_id,
        "node_state": node_state,
        "input_projection": input_projection,
        "candidate_output": None,
        "prompt_ref": None if prompt_ref is None else prompt_ref_to_mapping(prompt_ref),
        "attempt_no": 1,
        "schema_repair_count": 0,
        "semantic_revision_count": 0,
        "failure_record": None,
        "disposition": None,
        "typed_result": None,
    }


def prompt_ref_to_mapping(prompt_ref: PromptReference) -> PromptRef:
    return {
        "prompt_bundle_version": prompt_ref.prompt_bundle_version,
        "prompt_id": prompt_ref.prompt_id,
        "prompt_version": prompt_ref.prompt_version,
        "content_hash": prompt_ref.content_hash,
        "agent_role": prompt_ref.agent_role,
        "subgraph_name": prompt_ref.subgraph_name,
        "node_name": prompt_ref.node_name,
        "node_state": prompt_ref.node_state,
        "purpose": prompt_ref.purpose,
        "input_schema_version": prompt_ref.input_schema_version,
        "output_schema_version": prompt_ref.output_schema_version,
    }


def merge_trace_context(
    state: GraphState,
    *,
    graph_profile: str,
    agent_subgraph_id: str,
    agent_role: str,
    agent_invocation_id: str,
    subgraph_namespace: str,
    node_name: str,
    llm_call_id: str | None = None,
    prompt_ref: PromptReference | None = None,
    agent_invocation_increment: int = 0,
    llm_call_increment: int = 0,
    repair_increment: int = 0,
    revision_increment: int = 0,
) -> dict[str, object]:
    current = cast(dict[str, object], state.get("trace_context", {}))
    node_log = list(cast(list[dict[str, object]], current.get("agent_node_log", [])))
    prompt_refs = list(cast(list[PromptRef], current.get("prompt_refs", [])))
    node_log.append(
        {
            "graph_profile": graph_profile,
            "agent_subgraph_id": agent_subgraph_id,
            "agent_role": agent_role,
            "agent_invocation_id": agent_invocation_id,
            "subgraph_namespace": subgraph_namespace,
            "node_name": node_name,
            "llm_call_id": llm_call_id,
        }
    )
    if prompt_ref is not None:
        prompt_refs.append(prompt_ref_to_mapping(prompt_ref))
    return {
        **current,
        "agent_invocation_count": _counter_value(current, "agent_invocation_count")
        + agent_invocation_increment,
        "llm_call_count": _counter_value(current, "llm_call_count") + llm_call_increment,
        "repair_count": _counter_value(current, "repair_count") + repair_increment,
        "revision_count": _counter_value(current, "revision_count") + revision_increment,
        "agent_node_log": node_log,
        "prompt_refs": prompt_refs,
    }


def record_llm_result(
    local_state: AgentLocalStateV1,
    llm_result: StructuredLLMResult,
) -> AgentLocalStateV1:
    updated = dict(local_state)
    candidate = llm_result.structured_output
    updated["candidate_output"] = candidate if isinstance(candidate, dict) else None
    updated["schema_repair_count"] = max(0, llm_result.structured_output_attempts - 1)
    return cast(AgentLocalStateV1, updated)


def _counter_value(item: dict[str, object], field: str) -> int:
    value = item.get(field, 0)
    if not isinstance(value, int):
        raise ValueError(f"trace_context {field} must be an integer")
    return value
