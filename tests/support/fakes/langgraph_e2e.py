"""External LLM boundary fake for real production LangGraph E2E certification."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from google_work_agent.ports.llm.structured_inference_contracts import (
    AvailabilityState,
    OutputSchemaDefinition,
    ProbeResult,
    PromptReference,
    ProviderResponsePayload,
)


@dataclass
class LangGraphE2EGeminiTransport:
    """Deterministic provider responses; all Product orchestration stays real."""

    invocations: list[dict[str, object]] = field(default_factory=list)
    crash_prompt_id: str | None = None
    crash_scenario: str | None = None
    _scenario_prompt_counts: dict[tuple[str, str], int] = field(default_factory=dict)

    def probe(self, *, api_key: str, timeout_seconds: int) -> ProbeResult:
        self.invocations.append(
            {
                "kind": "probe",
                "api_key_length": len(api_key),
                "timeout_seconds": timeout_seconds,
            }
        )
        return ProbeResult(availability=AvailabilityState.AVAILABLE)

    def invoke_structured(
        self,
        *,
        model_id: str,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        timeout_seconds: int,
        api_key: str,
        instruction_text: str,
        sampling_temperature: float | None = None,
    ) -> ProviderResponsePayload:
        del output_schema, instruction_text, sampling_temperature
        prompt_id = prompt_ref.prompt_id
        scenario = _scenario(prompt_input)
        key = (scenario, prompt_id)
        self._scenario_prompt_counts[key] = self._scenario_prompt_counts.get(key, 0) + 1
        self.invocations.append(
            {
                "kind": "invoke",
                "model_id": model_id,
                "prompt_id": prompt_id,
                "scenario": scenario,
                "prompt_input": dict(prompt_input),
                "timeout_seconds": timeout_seconds,
                "api_key_length": len(api_key),
            }
        )
        if prompt_id == self.crash_prompt_id and (
            self.crash_scenario is None or scenario == self.crash_scenario
        ):
            # Simulate abrupt process loss at an external boundary. BaseException
            # intentionally bypasses Product failure/recovery translation, just
            # as an actual process termination would.
            raise SystemExit("simulated E2E process loss")
        output = _respond(
            prompt_id,
            prompt_input,
            scenario=scenario,
            call_no=self._scenario_prompt_counts[key],
        )
        return ProviderResponsePayload(
            content=json.dumps(output, sort_keys=True),
            model=model_id,
            provider_request_id=f"e2e-{len(self.invocations)}",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )


def _respond(
    prompt_id: str,
    prompt_input: Mapping[str, object],
    *,
    scenario: str,
    call_no: int,
) -> dict[str, object]:
    base = _base_projection(prompt_input)
    if prompt_id == "request_understanding.identify_goal":
        request_text = str(base["user_request"])
        return {
            "goal": request_text,
            "completion_conditions": ["E2E terminal outcome"],
            "constraints": [],
            "requested_effect_hints": [] if scenario == "ANSWER_ONLY" else [_effect_for(scenario)],
            "requested_resource_hints": _resource_hints(scenario),
            "analysis_requirement": "NONE",
        }
    if prompt_id == "request_understanding.detect_ambiguity":
        needs_confirmation = scenario == "RESTART_RESUME" and not isinstance(
            base.get("confirmation_response"), Mapping
        )
        return {
            "requires_confirmation": needs_confirmation,
            "missing_information_owner": "USER" if needs_confirmation else "NONE",
            "reason_codes": ["MISSING_USER_CHOICE"] if needs_confirmation else [],
            "missing_fields": ["target"] if needs_confirmation else [],
        }
    if prompt_id == "tool_routing.determine_io_resources":
        inputs, outputs, effects = _route_semantics(scenario)
        return {
            "schema_version": 1,
            "input_resource_types": inputs,
            "output_resource_types": outputs,
            "output_effects": effects,
            "disposition": "NO_TOOL_NEEDED" if not inputs and not outputs else "ROUTE_READY",
        }
    if prompt_id == "tool_routing.select_tool_if_needed":
        route = cast(Mapping[str, object], base["route_candidate"])
        candidates = cast(list[Mapping[str, str]], base["registered_candidates"])
        selected = _select_tool(
            str(route["resource_type"]),
            str(route["effect"]),
            [item["tool_id"] for item in candidates],
        )
        return {
            "schema_version": 1,
            "route_id": str(route["route_id"]),
            "selected_tool_id": selected,
        }
    if prompt_id == "retrieval.plan_query":
        routes = cast(list[Mapping[str, object]], base["input_routes"])
        searchable_routes = [route for route in routes if _has_search_tool(route)]
        route_queries = [_route_query(route) for route in searchable_routes]
        route_ids = [str(route["route_id"]) for route in searchable_routes]
        return {
            "schema_version": 2,
            "route_queries": route_queries,
            "required_information": ["E2E evidence"],
            "retrieval_order": route_ids,
        }
    if prompt_id == "retrieval.select_evidence":
        ranked = cast(list[Mapping[str, object]], base.get("ranked_segments", []))
        selected_segment_ids = [str(item["segment_id"]) for item in ranked]
        return {
            "schema_version": 2,
            "evidence_drafts": [
                {
                    "segment_id": segment_id,
                    "role": "SUPPORTS",
                    "relevance_reason": "E2E source evidence",
                }
                for segment_id in selected_segment_ids
            ],
            "selected_segment_ids": selected_segment_ids,
            "excluded_segment_ids": [],
        }
    if prompt_id == "retrieval.assess_sufficiency":
        return {"schema_version": 2, "status": "SUFFICIENT", "issues": []}
    if prompt_id == "work_analysis.extract_work_facts":
        return {"fact_candidates": []}
    if prompt_id in {
        "work_analysis.resolve_entity_relations",
        "work_analysis.resolve_temporal_dependencies",
        "work_analysis.detect_duplicate_conflict_candidates",
    }:
        return {"relation_candidates": []}
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
            "action_necessity_candidate": "REQUIRED",
            "action_necessity_reason": "User requested an E2E write",
            "evidence_refs": [],
        }
    if prompt_id == "planning.outline_answer":
        refs = _evidence_refs(base)
        return {"sections": ["E2E result"], "evidence_refs": refs}
    if prompt_id == "planning.compose_answer":
        outline = cast(Mapping[str, object], base["answer_outline"])
        return {
            "schema_version": 2,
            "answer": _answer_for(scenario),
            "evidence_refs": list(cast(list[str], outline["evidence_refs"])),
        }
    if prompt_id == "planning.draft_action_objective_per_output_route":
        route = cast(Mapping[str, object], base["output_route"])
        return {
            "schema_version": 1,
            "route_id": str(route["route_id"]),
            "objective": f"E2E {scenario}",
            "target_semantics": str(route["resource_type"]),
            "scope_constraints": ["Use only the frozen output route"],
            "evidence_refs": _evidence_refs(base),
        }
    if prompt_id == "planning.compose_arguments_per_output_route":
        route = cast(Mapping[str, object], base["output_route"])
        return {
            "schema_version": 1,
            "route_id": str(route["route_id"]),
            "arguments": _arguments(str(route["resource_type"]), scenario),
            "evidence_refs": _evidence_refs(base),
        }
    if prompt_id.startswith("review.inspect_"):
        findings: list[dict[str, object]] = []
        if (
            scenario == "REVIEW_BACK_EDGE"
            and prompt_id == "review.inspect_action_scope_and_route"
            and call_no == 1
        ):
            action_ids, route_ids = _action_and_route_ids(base)
            findings.append(
                {
                    "dimension": prompt_id,
                    "code": "E2E_ACTION_REVISION",
                    "finding_kind": "ISSUE",
                    "description": "Exercise the real bounded Review back-edge",
                    "evidence_refs": [],
                    "affected_action_ids": action_ids,
                    "affected_route_ids": route_ids,
                    "required_information": [],
                }
            )
        return {"schema_version": 1, "dimension": prompt_id, "findings": findings}
    if prompt_id == "review.recheck_affected_dimensions":
        dimensions = cast(list[str], base["affected_dimensions"])
        return {
            "schema_version": 1,
            "affected_dimensions": dimensions,
            "findings": [],
        }
    raise AssertionError(f"unhandled E2E Product Prompt: {prompt_id}")


def _base_projection(prompt_input: Mapping[str, object]) -> Mapping[str, object]:
    value = prompt_input.get("base_projection")
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else prompt_input


def _scenario(value: object) -> str:
    serialized = json.dumps(value, sort_keys=True, default=str).upper()
    for scenario in (
        "RETRIEVAL_CACHE_LOSS",
        "UNKNOWN_RESULT_RECOVERY",
        "VERIFICATION_MISMATCH",
        "CONTEXT_ADJUSTMENT",
        "PARTIAL_APPROVAL",
        "CALENDAR_WRITE",
        "PROCESS_RESTART",
        "RESPONSE_LOSS",
        "MCP_FAILURE",
        "REVIEW_BACK_EDGE",
        "RESTART_RESUME",
        "UNKNOWN_RESULT",
        "APPROVED_WRITE",
        "FAILED_RETRY",
        "ANSWER_ONLY",
        "CALENDAR_READ",
        "TASKS_READ",
        "GMAIL_READ",
        "REJECTION",
        "RECOVERY",
        "REAUTH",
        "CANCEL",
    ):
        if scenario in serialized:
            return scenario
    return "ANSWER_ONLY"


def _answer_for(scenario: str) -> str:
    return {
        "ANSWER_ONLY": "현재 요청을 처리할 준비가 되어 있습니다.",
        "GMAIL_READ": "선택한 메일의 핵심 내용은 deterministic Gmail evidence입니다.",
        "TASKS_READ": "확인한 태스크의 핵심 내용은 E2E task입니다.",
        "CALENDAR_READ": "확인한 일정의 핵심 내용은 E2E event입니다.",
    }.get(scenario, f"E2E 결과를 정리했습니다: {scenario}")


def _effect_for(scenario: str) -> str:
    if scenario == "ANSWER_ONLY":
        return "READ"
    if scenario.endswith("_READ"):
        return "READ"
    return "CREATE"


def _resource_hints(scenario: str) -> list[str]:
    inputs, outputs, _ = _route_semantics(scenario)
    aliases = {
        "EMAIL": "GMAIL_THREAD",
        "TASK": "TASK",
        "CALENDAR": "CALENDAR_EVENT",
    }
    return list(dict.fromkeys(aliases[item] for item in [*inputs, *outputs]))


def _route_semantics(scenario: str) -> tuple[list[str], list[str], list[str]]:
    if scenario == "ANSWER_ONLY":
        return [], [], []
    if scenario == "GMAIL_READ":
        return ["EMAIL"], [], []
    if scenario == "TASKS_READ":
        return ["TASK"], [], []
    if scenario == "CALENDAR_READ":
        return ["CALENDAR"], [], []
    if scenario == "PARTIAL_APPROVAL":
        return ["TASK", "CALENDAR"], ["TASK", "CALENDAR"], ["CREATE", "CREATE"]
    if scenario in {"CALENDAR_WRITE", "VERIFICATION_MISMATCH", "RECOVERY"}:
        return ["CALENDAR"], ["CALENDAR"], ["CREATE"]
    return ["TASK"], ["TASK"], ["CREATE"]


def _select_tool(resource_type: str, effect: str, candidates: list[str]) -> str:
    preferences = {
        ("EMAIL", "READ"): "gmail_search_threads",
        ("TASK", "READ"): "tasks_list_tasks",
        ("CALENDAR", "READ"): "calendar_list_events",
    }
    preferred = preferences.get((resource_type, effect))
    if preferred in candidates:
        return cast(str, preferred)
    return candidates[0]


def _route_query(route: Mapping[str, object]) -> dict[str, object]:
    resource_type = str(route["resource_type"])
    if resource_type == "EMAIL":
        constraint: dict[str, object] = {
            "kind": "KEYWORD",
            "terms": ["E2E"],
            "match_mode": "ANY",
        }
    else:
        container_refs = cast(list[str], route.get("container_refs", []))
        if not container_refs:
            raise AssertionError(f"{resource_type} E2E route did not receive a validated container")
        constraint = {"kind": "CONTAINER_REF", "container_refs": [container_refs[0]]}
    return {
        "route_id": str(route["route_id"]),
        "operation": "SEARCH",
        "reason_codes": ["USER_REQUEST"],
        "search_spec": {"mode": "INITIAL", "constraints": [constraint]},
        "detail_candidate_ref": None,
    }


def _has_search_tool(route: Mapping[str, object]) -> bool:
    tools = cast(list[str], route.get("allowed_read_tool_ids", []))
    return any("search" in tool or "list" in tool for tool in tools)


def _evidence_refs(prompt_input: Mapping[str, object]) -> list[str]:
    evidence = cast(list[Mapping[str, object]], prompt_input.get("evidence", []))
    return [
        str(ref)
        for item in evidence
        for ref in (item.get("evidence_ref") or item.get("evidence_id") or item.get("id"),)
        if isinstance(ref, str) and ref
    ]


def _arguments(resource_type: str, scenario: str) -> dict[str, object]:
    payload: dict[str, object] = {"title": f"E2E {scenario}"}
    if resource_type == "CALENDAR_EVENT":
        payload.update(
            {
                "start": "2026-09-03T09:00:00+09:00",
                "end": "2026-09-03T10:00:00+09:00",
            }
        )
    return {"payload": payload}


def _action_and_route_ids(prompt_input: Mapping[str, object]) -> tuple[list[str], list[str]]:
    planning = cast(Mapping[str, object], prompt_input.get("planning_result", {}))
    actions = cast(list[Mapping[str, object]], planning.get("actions", []))
    return (
        [str(item["action_id"]) for item in actions if item.get("action_id")],
        [str(item["route_id"]) for item in actions if item.get("route_id")],
    )


__all__ = ["LangGraphE2EGeminiTransport"]
