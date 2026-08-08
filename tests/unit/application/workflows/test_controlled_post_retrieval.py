from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from tests.support.prompt_manifests import write_runtime_active_manifest

from google_work_agent.application.workflows import (
    E06B_ANALYSIS_PLANNING_OUTPUT_SCHEMA,
    PLAN_REVIEW_OUTPUT_SCHEMA,
    ControlledPostRetrievalReplayError,
    ControlledPostRetrievalReplayRunner,
)
from google_work_agent.application.workflows.controlled_post_retrieval import (
    _calculate_evaluation_environment_hash,
)
from google_work_agent.ports import (
    ActualRuntime,
    OutputSchemaDefinition,
    PromptReference,
    RequestedRuntimeMode,
    StructuredLLMResult,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parents[4]
    / "experiments"
    / "datasets"
    / "google_workspace"
    / "controlled_post_retrieval"
    / "context_ready_v1"
    / "CTXREADY-CORE-002"
)
PROMPT_IDS = {
    "analysis.analyze",
    "planning.answer_only",
    "planning.draft_plan",
    "review.inspect",
    "e06b.b1.analysis_planning.initial",
    "e06b.b1.self_review.initial",
    "e06b.b2.analysis_planning.initial",
}


@dataclass
class FakeLLMRuntime:
    queued: deque[StructuredLLMResult] = field(default_factory=deque)
    calls: list[dict[str, object]] = field(default_factory=list)

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: dict[str, object],
        output_schema: OutputSchemaDefinition,
        trace_context: object,
    ) -> StructuredLLMResult:
        self.calls.append(
            {
                "prompt_ref": prompt_ref,
                "prompt_input": prompt_input,
                "output_schema": output_schema,
                "trace_context": trace_context,
            }
        )
        return self.queued.popleft()


def test_plan_review_output_schema_requires_additional_acquisition_request() -> None:
    required = PLAN_REVIEW_OUTPUT_SCHEMA.json_schema["required"]
    assert isinstance(required, list)
    assert "additional_acquisition_request" in required


def test_e06b_analysis_planning_schema_supports_answer_only_projection() -> None:
    required = E06B_ANALYSIS_PLANNING_OUTPUT_SCHEMA.json_schema["required"]
    assert isinstance(required, list)
    assert "planning_result" in required


def test_stage18_schema_audit_keeps_runtime_contract_fields_locked() -> None:
    request_intent_schema = _load_json(
        Path("experiments/datasets/google_workspace/schemas/request-intent.schema.json")
    )
    profile_single_schema = _load_json(
        Path(
            "experiments/datasets/google_workspace/schemas/"
            "profile-single-post-retrieval-output.schema.json"
        )
    )
    profile_three_schema = _load_json(
        Path(
            "experiments/datasets/google_workspace/schemas/profile-three-stage2-output.schema.json"
        )
    )
    action_plan_schema = _load_json(
        Path("experiments/datasets/google_workspace/schemas/action-plan-draft.schema.json")
    )
    plan_review_schema = _load_json(
        Path("experiments/datasets/google_workspace/schemas/plan-review-output.schema.json")
    )

    assert request_intent_schema["required"] == [
        "schema_version",
        "goal",
        "completion_criteria",
        "semantic_constraints",
        "ambiguity",
        "unsupported_scope",
    ]
    assert profile_single_schema["required"] == [
        "schema_version",
        "context_result",
        "analysis_result",
        "planning_result",
        "self_review",
    ]
    assert profile_three_schema["required"] == [
        "schema_version",
        "context_result",
        "analysis_result",
        "planning_result",
    ]
    assert action_plan_schema["required"] == [
        "schema_version",
        "status",
        "plan_id",
        "summary",
        "objective",
        "actions",
        "evidence_refs",
        "resource_refs",
        "confirmation",
    ]
    assert plan_review_schema["required"] == [
        "schema_version",
        "status",
        "summary",
        "issues",
        "confirmation",
        "blockers",
        "additional_acquisition_request",
    ]


def test_controlled_replay_runner_executes_native_b1_b2_b3_topologies(
    tmp_path: Path,
) -> None:
    manifest_path = write_runtime_active_manifest(tmp_path, prompt_ids=PROMPT_IDS)
    model_input = _load_json(FIXTURE_DIR / "input.json")
    gold = _load_json(FIXTURE_DIR / "gold.json")
    evaluation_item = _load_json(FIXTURE_DIR / "evaluation-item.json")

    b1_runner = ControlledPostRetrievalReplayRunner(
        llm_runtime=FakeLLMRuntime(
            deque(
                [
                    _llm_result(_b1_analysis_planning_output()),
                    _llm_result(_review_output()),
                ]
            )
        ),
        manifest_path=manifest_path,
    )
    b1_result, b1_node = b1_runner.run(
        experiment_id="EXP-E06B-CONTROLLED-POST-RET",
        candidate_config=_load_json(
            Path("experiments/candidates/cand-e06b-b1-integrated.template.json")
        ),
        evaluation_item=evaluation_item,
        model_input=model_input,
        gold=gold,
    )

    assert b1_result.agent_invocation_count == 1
    assert b1_result.llm_call_count == 2
    assert b1_result.graph_profile == "E06B_B1_INTEGRATED"
    assert b1_result.context_snapshot_id == model_input["context_snapshot_id"]
    assert b1_node["graph_profile"] == "E06B_B1_INTEGRATED"
    assert b1_node["agent_invocation_count"] == 1
    assert b1_node["llm_call_count"] == 2

    b2_runner = ControlledPostRetrievalReplayRunner(
        llm_runtime=FakeLLMRuntime(
            deque(
                [
                    _llm_result(_b2_analysis_planning_output()),
                    _llm_result(_review_output()),
                ]
            )
        ),
        manifest_path=manifest_path,
    )
    b2_result, b2_node = b2_runner.run(
        experiment_id="EXP-E06B-CONTROLLED-POST-RET",
        candidate_config=_load_json(
            Path("experiments/candidates/cand-e06b-b2-staged.template.json")
        ),
        evaluation_item=evaluation_item,
        model_input=model_input,
        gold=gold,
    )

    assert b2_result.agent_invocation_count == 2
    assert b2_result.llm_call_count == 2
    assert b2_result.graph_profile == "E06B_B2_STAGED"
    assert b2_node["graph_profile"] == "E06B_B2_STAGED"
    assert b2_node["agent_invocation_count"] == 2
    assert b2_node["llm_call_count"] == 2

    b3_runner = ControlledPostRetrievalReplayRunner(
        llm_runtime=FakeLLMRuntime(
            deque(
                [
                    _llm_result(_analysis_result()),
                    _llm_result(_answer_output()),
                    _llm_result(_review_output()),
                ]
            )
        ),
        manifest_path=manifest_path,
    )
    b3_result, b3_node = b3_runner.run(
        experiment_id="EXP-E06B-CONTROLLED-POST-RET",
        candidate_config=_load_json(
            Path("experiments/candidates/cand-e06b-b3-specialized.template.json")
        ),
        evaluation_item=evaluation_item,
        model_input=model_input,
        gold=gold,
    )

    assert b3_result.agent_invocation_count == 3
    assert b3_result.llm_call_count == 3
    assert b3_result.graph_profile == "E06B_B3_SPECIALIZED"
    assert b3_node["graph_profile"] == "E06B_B3_SPECIALIZED"
    assert b3_node["agent_invocation_count"] == 3
    assert b3_node["llm_call_count"] == 3
    assert isinstance(b3_node, dict)
    assert b3_node["required_field_preservation_rate"] == 1.0
    assert b3_node["evidence_id_preservation_rate"] == 1.0
    assert b3_node["constraint_loss_count"] == 0
    assert b3_node["contradiction_introduced"] is False


def test_controlled_replay_runner_rejects_mismatched_environment_hash(
    tmp_path: Path,
) -> None:
    manifest_path = write_runtime_active_manifest(tmp_path, prompt_ids=PROMPT_IDS)
    runner = ControlledPostRetrievalReplayRunner(
        llm_runtime=FakeLLMRuntime(
            deque(
                [
                    _llm_result(_b1_analysis_planning_output()),
                    _llm_result(_review_output()),
                ]
            )
        ),
        manifest_path=manifest_path,
    )
    model_input = _load_json(FIXTURE_DIR / "input.json")
    gold = _load_json(FIXTURE_DIR / "gold.json")
    evaluation_item = _load_json(FIXTURE_DIR / "evaluation-item.json")
    candidate_config = _load_json(
        Path("experiments/candidates/cand-e06b-b1-integrated.template.json")
    )
    candidate_config["evaluation_environment"]["evaluation_environment_hash"] = "deadbeef"

    try:
        runner.run(
            experiment_id="EXP-E06B-CONTROLLED-POST-RET",
            candidate_config=candidate_config,
            evaluation_item=evaluation_item,
            model_input=model_input,
            gold=gold,
        )
    except ControlledPostRetrievalReplayError as error:
        assert "evaluation_environment_hash mismatch" in str(error)
    else:
        raise AssertionError("expected ControlledPostRetrievalReplayError")


def test_controlled_replay_environment_hash_is_sensitive_to_profile_and_timeout() -> None:
    candidate_config = _load_json(
        Path("experiments/candidates/cand-e06b-b1-integrated.template.json")
    )
    evaluation_item = _load_json(FIXTURE_DIR / "evaluation-item.json")

    baseline = _calculate_evaluation_environment_hash(
        candidate_config=candidate_config,
        evaluation_item=evaluation_item,
    )

    timeout_changed = _load_json(
        Path("experiments/candidates/cand-e06b-b1-integrated.template.json")
    )
    timeout_changed["evaluation_environment"]["api_llm_timeout_seconds"] = 90
    timeout_hash = _calculate_evaluation_environment_hash(
        candidate_config=timeout_changed,
        evaluation_item=evaluation_item,
    )

    profile_changed = _load_json(
        Path("experiments/candidates/cand-e06b-b1-integrated.template.json")
    )
    profile_changed["graph_profile_spec"]["profile_id"] = "E06B_B2_STAGED"
    profile_changed["graph_version"] = "E06B_B2_STAGED"
    profile_hash = _calculate_evaluation_environment_hash(
        candidate_config=profile_changed,
        evaluation_item=evaluation_item,
    )

    assert baseline != timeout_hash
    assert baseline != profile_hash


def test_controlled_replay_runner_rejects_non_zero_google_read_boundary(
    tmp_path: Path,
) -> None:
    manifest_path = write_runtime_active_manifest(tmp_path, prompt_ids=PROMPT_IDS)
    runner = ControlledPostRetrievalReplayRunner(
        llm_runtime=FakeLLMRuntime(
            deque(
                [
                    _llm_result(_b1_analysis_planning_output()),
                    _llm_result(_review_output()),
                ]
            )
        ),
        manifest_path=manifest_path,
    )
    model_input = _load_json(FIXTURE_DIR / "input.json")
    gold = _load_json(FIXTURE_DIR / "gold.json")
    evaluation_item = _load_json(FIXTURE_DIR / "evaluation-item.json")
    evaluation_item["execution_contract"]["google_read_call_count"] = 1

    try:
        runner.run(
            experiment_id="EXP-E06B-CONTROLLED-POST-RET",
            candidate_config=_load_json(
                Path("experiments/candidates/cand-e06b-b1-integrated.template.json")
            ),
            evaluation_item=evaluation_item,
            model_input=model_input,
            gold=gold,
        )
    except ControlledPostRetrievalReplayError as error:
        assert "Google Read count 0" in str(error)
    else:
        raise AssertionError("expected ControlledPostRetrievalReplayError")


def test_controlled_replay_handoff_metrics_detect_forbidden_action_contradiction(
    tmp_path: Path,
) -> None:
    manifest_path = write_runtime_active_manifest(tmp_path, prompt_ids=PROMPT_IDS)
    runner = ControlledPostRetrievalReplayRunner(
        llm_runtime=FakeLLMRuntime(
            deque(
                [
                    _llm_result(_analysis_result()),
                    _llm_result(_forbidden_plan_output()),
                    _llm_result(_review_output()),
                ]
            )
        ),
        manifest_path=manifest_path,
    )
    model_input = _load_json(FIXTURE_DIR / "input.json")
    gold = _load_json(FIXTURE_DIR / "gold.json")
    gold["gold"]["expected_answer_type"] = "PLAN"
    evaluation_item = _load_json(FIXTURE_DIR / "evaluation-item.json")
    candidate_config = _load_json(
        Path("experiments/candidates/cand-e06b-b3-specialized.template.json")
    )

    _, node = runner.run(
        experiment_id="EXP-E06B-CONTROLLED-POST-RET",
        candidate_config=candidate_config,
        evaluation_item=evaluation_item,
        model_input=model_input,
        gold=gold,
    )

    assert node["required_field_preservation_rate"] == 1.0
    assert node["evidence_id_preservation_rate"] == 1.0
    assert node["constraint_loss_count"] >= 1
    assert node["contradiction_introduced"] is True


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _llm_result(payload: object) -> StructuredLLMResult:
    return StructuredLLMResult(
        structured_output=payload,
        provider="fake",
        model="fake-model",
        requested_mode=RequestedRuntimeMode.AUTO,
        actual_runtime=ActualRuntime.API_LLM,
        input_tokens=11,
        output_tokens=19,
        total_tokens=30,
        latency_ms=7,
        estimated_cost_usd=None,
        fallback_reason=None,
        structured_output_attempts=1,
        provider_request_id="provider-request-1",
        safe_error_code=None,
    )


def _analysis_result() -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "COMPLETE",
        "summary": "The frozen context is sufficient to answer.",
        "findings": [
            {
                "schema_version": 1,
                "finding_id": "finding-1",
                "kind": "FACT",
                "statement": "The final schedule is fixed on August 19.",
                "evidence_refs": ["EVD-SEG-GM-A-002-1"],
                "resource_refs": ["resource:GM-A-002"],
                "segment_refs": ["SEG-GM-A-002"],
                "related_resource_handles": ["resource:GM-A-002"],
                "reason_codes": ["EVIDENCE_SUPPORTED"],
            }
        ],
        "missing_information": [],
        "confirmation": None,
        "blockers": [],
        "evidence_refs": ["EVD-SEG-GM-A-002-1"],
        "resource_refs": [
            {
                "resource_handle": "resource:GM-A-002",
                "resource_type": "snapshot_resource",
                "resource_id": "GM-A-002",
            }
        ],
        "segment_refs": [
            {
                "segment_id": "SEG-GM-A-002",
                "resource_handle": "resource:GM-A-002",
            }
        ],
    }


def _answer_output() -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "ANSWER_ONLY",
        "answer": (
            "Atlas final release is scheduled for August 19 and the email confirms "
            "it replaces the earlier August 18 draft."
        ),
        "evidence_refs": ["EVD-SEG-GM-A-002-1"],
        "resource_refs": [
            {
                "resource_handle": "resource:GM-A-002",
                "resource_type": "snapshot_resource",
                "resource_id": "GM-A-002",
            }
        ],
        "reason_codes": ["EVIDENCE_SUPPORTED"],
        "confirmation": None,
        "blockers": [],
    }


def _plan_output() -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "PLAN_READY",
        "plan_id": "plan-1",
        "summary": "Read the authoritative Gmail thread only.",
        "objective": "Use the frozen Gmail evidence without other products.",
        "actions": [
            {
                "schema_version": 1,
                "action_id": "action-1",
                "position": 1,
                "effect": "READ",
                "tool_name": "gmail_get_thread",
                "arguments": {"thread_id": "GM-A-002"},
                "expected": {"resource_type": "gmail_thread"},
                "evidence_refs": ["EVD-SEG-GM-A-002-1"],
                "resource_refs": ["resource:GM-A-002"],
                "target_resource_ref_id": None,
                "depends_on_action_ids": [],
                "user_visible_reason": "Use the selected Gmail thread as the only evidence source.",
            }
        ],
        "evidence_refs": ["EVD-SEG-GM-A-002-1"],
        "resource_refs": [
            {
                "resource_handle": "resource:GM-A-002",
                "resource_type": "snapshot_resource",
                "resource_id": "GM-A-002",
            }
        ],
        "confirmation": None,
    }


def _forbidden_plan_output() -> dict[str, object]:
    payload = _plan_output()
    payload["actions"][0]["tool_name"] = "gmail_send"
    payload["actions"][0]["effect"] = "SEND"
    return payload


def _review_output() -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "PASS",
        "summary": (
            "The answer or plan is grounded in the frozen context and preserves the constraints."
        ),
        "issues": [],
        "confirmation": None,
        "blockers": [],
        "additional_acquisition_request": None,
    }


def _b1_analysis_planning_output() -> dict[str, object]:
    return {
        "schema_version": 1,
        "analysis_result": _analysis_result(),
        "planning_result": {
            "schema_version": 1,
            "status": "ANSWER_ONLY",
            "answer_draft": _answer_output(),
            "plan_draft": None,
        },
    }


def _b2_analysis_planning_output() -> dict[str, object]:
    return {
        "schema_version": 1,
        "analysis_result": _analysis_result(),
        "planning_result": {
            "schema_version": 1,
            "status": "PLAN_READY",
            "answer_draft": None,
            "plan_draft": _plan_output(),
        },
    }
