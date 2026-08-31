from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest
from evaluation.compat.controlled_post_retrieval import (
    E06B_ANALYSIS_PLANNING_OUTPUT_SCHEMA,
    ControlledPostRetrievalReplayError,
    ControlledPostRetrievalReplayRunner,
    _build_evaluation_environment_hash_payload,
    _build_fixed_environment_payload,
    _calculate_evaluation_environment_hash,
)
from evaluation.compat.plan_review import (
    PLAN_REVIEW_OUTPUT_SCHEMA,
)
from tests.support.prompt_manifests import write_manifest_with_legacy_profile_slots

from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.ports.llm import (
    ActualRuntime,
    OutputSchemaDefinition,
    PromptReference,
    RequestedRuntimeMode,
    StructuredLLMResult,
)
from google_work_agent.ports.system.contracts.observability import ObservabilityContext

FIXTURE_DIR = (
    Path(__file__).resolve().parents[3]
    / "evaluation"
    / "compat"
    / "experiments"
    / "datasets"
    / "google_workspace"
    / "controlled_post_retrieval"
    / "context_ready_v1"
    / "CTXREADY-CORE-002"
)
PROMPT_IDS = {
    "work_analysis.analyze",
    "planning.compose_answer",
    "planning.compose_arguments",
    "review.inspect",
    # e06b.* are E06-B controlled-experiment candidate prompts -- a
    # separate Evaluation artifact bundle, not product manifest slots;
    # write_runtime_active_manifest only activates slots that exist in the
    # canonical product manifest, so these three stay unresolvable until
    # that Evaluation artifact bundle exists (EVALUATION_ARTIFACT_PENDING).
    "e06b.b1.analysis_planning.initial",
    "e06b.b1.self_review.initial",
    "e06b.b2.analysis_planning.initial",
}
E06B_PROMPT_IDS = {prompt_id for prompt_id in PROMPT_IDS if prompt_id.startswith("e06b.")}


def _runtime_active_manifest(tmp_path: Path) -> Path:
    return write_manifest_with_legacy_profile_slots(
        tmp_path,
        legacy_prompt_ids=E06B_PROMPT_IDS,
        active_prompt_ids=PROMPT_IDS - E06B_PROMPT_IDS,
        draft_prompt_ids=(),
        active_legacy_prompt_ids=E06B_PROMPT_IDS,
    )


@dataclass
class FakeLLMRuntime:
    queued: deque[StructuredLLMResult] = field(default_factory=deque)
    calls: list[dict[str, object]] = field(default_factory=list)

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate: Callable[[object], object] | None = None,
    ) -> StructuredLLMResult:
        del semantic_validate
        self.calls.append(
            {
                "prompt_ref": prompt_ref,
                "prompt_input": dict(prompt_input),
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


def test_canonical_schema_artifacts_keep_runtime_contract_fields_locked() -> None:
    schema_root = Path(
        "evaluation/compat/experiments/datasets/google_workspace/canonical_rebase_v7/schemas"
    )
    request_intent_schema = _load_json(schema_root / "request-intent-v2.schema.json")
    plan_review_schema = _load_json(schema_root / "plan-review-result-v2.schema.json")

    assert request_intent_schema["required"] == [
        "schema_version",
        "meta",
        "goal",
        "completion_conditions",
        "constraints",
        "requested_effect_hints",
        "requested_resource_hints",
        "analysis_requirement",
        "ambiguity",
    ]
    assert plan_review_schema["required"] == ["schema_version", "status"]


def test_e06_candidates_keep_semantic_bundle_and_responsibility_parity() -> None:
    candidates = [
        _load_json(
            Path("evaluation/compat/experiments/candidates/cand-e06b-b1-integrated.template.json")
        ),
        _load_json(
            Path("evaluation/compat/experiments/candidates/cand-e06b-b2-staged.template.json")
        ),
        _load_json(
            Path("evaluation/compat/experiments/candidates/cand-e06b-b3-specialized.template.json")
        ),
    ]

    assert {candidate["prompt_semantic_bundle_version"] for candidate in candidates} == {
        "semantic-r8.4-v1"
    }
    assert {
        _nested_mapping(candidate, "graph_profile_spec")["semantic_responsibility_map_version"]
        for candidate in candidates
    } == {"semantic-responsibility-r8.2-v1"}


def test_controlled_replay_runner_executes_native_b1_b2_b3_topologies(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest(tmp_path)
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
            Path("evaluation/compat/experiments/candidates/cand-e06b-b1-integrated.template.json")
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
            Path("evaluation/compat/experiments/candidates/cand-e06b-b2-staged.template.json")
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
            Path("evaluation/compat/experiments/candidates/cand-e06b-b3-specialized.template.json")
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
    manifest_path = _runtime_active_manifest(tmp_path)
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
        Path("evaluation/compat/experiments/candidates/cand-e06b-b1-integrated.template.json")
    )
    _nested_mapping(candidate_config, "evaluation_environment")["evaluation_environment_hash"] = (
        "deadbeef"
    )

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
        Path("evaluation/compat/experiments/candidates/cand-e06b-b1-integrated.template.json")
    )
    evaluation_item = _load_json(FIXTURE_DIR / "evaluation-item.json")
    fixture_snapshot_id = "FW-D-001"

    baseline = _calculate_evaluation_environment_hash(
        candidate_config=candidate_config,
        evaluation_item=evaluation_item,
        fixture_snapshot_id=fixture_snapshot_id,
    )

    timeout_changed = _load_json(
        Path("evaluation/compat/experiments/candidates/cand-e06b-b1-integrated.template.json")
    )
    _nested_mapping(timeout_changed, "evaluation_environment")["api_llm_timeout_seconds"] = 90
    timeout_hash = _calculate_evaluation_environment_hash(
        candidate_config=timeout_changed,
        evaluation_item=evaluation_item,
        fixture_snapshot_id=fixture_snapshot_id,
    )

    profile_changed = _load_json(
        Path("evaluation/compat/experiments/candidates/cand-e06b-b1-integrated.template.json")
    )
    _nested_mapping(profile_changed, "graph_profile_spec")["profile_id"] = "E06B_B2_STAGED"
    profile_changed["graph_version"] = "E06B_B2_STAGED"
    profile_hash = _calculate_evaluation_environment_hash(
        candidate_config=profile_changed,
        evaluation_item=evaluation_item,
        fixture_snapshot_id=fixture_snapshot_id,
    )

    assert baseline != timeout_hash
    assert baseline != profile_hash


def test_controlled_replay_environment_hash_is_stable_under_key_reordering() -> None:
    evaluation_item = _load_json(FIXTURE_DIR / "evaluation-item.json")
    fixture_snapshot_id = "FW-D-001"
    payload = _build_evaluation_environment_hash_payload(
        candidate_config=_load_json(
            Path("evaluation/compat/experiments/candidates/cand-e06b-b1-integrated.template.json")
        ),
        evaluation_item=evaluation_item,
        fixture_snapshot_id=fixture_snapshot_id,
    )
    reordered = {
        "runtime": payload["runtime"],
        "graph_profile": payload["graph_profile"],
        "prompt_semantic_bundle_version": payload["prompt_semantic_bundle_version"],
        "fixture_snapshot_id": payload["fixture_snapshot_id"],
        "evaluation_environment": payload["evaluation_environment"],
        "dataset_version": payload["dataset_version"],
        "execution_contract": payload["execution_contract"],
        "policy_version": payload["policy_version"],
        "tool_schema_version": payload["tool_schema_version"],
        "context_ready_contract_version": payload["context_ready_contract_version"],
    }

    assert calculate_canonical_json_hash(payload) == calculate_canonical_json_hash(reordered)


@pytest.mark.parametrize(
    ("field_path", "mutated_value"),
    [
        ("runtime.model", "RESOLVE_E01_ALTERNATE"),
        ("runtime.parameters.reasoning_budget", "high"),
        ("evaluation_environment.hardware_profile_id", "LOCAL_GPU_A100"),
        ("evaluation_environment.llm_concurrency", 2),
        ("evaluation_environment.api_llm_timeout_seconds", 90),
        ("fixture_snapshot_id", "FW-D-999"),
        ("tool_schema_version", "v2.7"),
        ("policy_version", "01-B-v2.5"),
        ("prompt_semantic_bundle_version", "semantic-r8.3-v2"),
    ],
)
def test_controlled_replay_environment_hash_changes_for_each_fixed_dimension(
    field_path: str,
    mutated_value: object,
) -> None:
    candidate_config = _load_json(
        Path("evaluation/compat/experiments/candidates/cand-e06b-b1-integrated.template.json")
    )
    evaluation_item = _load_json(FIXTURE_DIR / "evaluation-item.json")
    fixture_snapshot_id = "FW-D-001"
    baseline = _calculate_evaluation_environment_hash(
        candidate_config=candidate_config,
        evaluation_item=evaluation_item,
        fixture_snapshot_id=fixture_snapshot_id,
    )
    mutated_candidate = _load_json(
        Path("evaluation/compat/experiments/candidates/cand-e06b-b1-integrated.template.json")
    )
    mutated_fixture_snapshot_id = fixture_snapshot_id

    if field_path == "fixture_snapshot_id":
        mutated_fixture_snapshot_id = str(mutated_value)
    else:
        _set_nested_value(mutated_candidate, field_path, mutated_value)

    mutated = _calculate_evaluation_environment_hash(
        candidate_config=mutated_candidate,
        evaluation_item=evaluation_item,
        fixture_snapshot_id=mutated_fixture_snapshot_id,
    )

    assert baseline != mutated


def test_controlled_replay_runner_rejects_non_zero_google_read_boundary(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest(tmp_path)
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
    _nested_mapping(evaluation_item, "execution_contract")["google_read_call_count"] = 1

    try:
        runner.run(
            experiment_id="EXP-E06B-CONTROLLED-POST-RET",
            candidate_config=_load_json(
                Path(
                    "evaluation/compat/experiments/candidates/cand-e06b-b1-integrated.template.json"
                )
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
    manifest_path = _runtime_active_manifest(tmp_path)
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
    _nested_mapping(gold, "gold")["expected_answer_type"] = "PLAN"
    evaluation_item = _load_json(FIXTURE_DIR / "evaluation-item.json")
    candidate_config = _load_json(
        Path("evaluation/compat/experiments/candidates/cand-e06b-b3-specialized.template.json")
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


def test_controlled_replay_handoff_metrics_detect_required_field_loss(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest(tmp_path)
    runner = ControlledPostRetrievalReplayRunner(
        llm_runtime=FakeLLMRuntime(
            deque(
                [
                    _llm_result(_analysis_result()),
                    _llm_result(_answer_output_missing_resource_ref()),
                    _llm_result(_review_output()),
                ]
            )
        ),
        manifest_path=manifest_path,
    )

    _, node = runner.run(
        experiment_id="EXP-E06B-CONTROLLED-POST-RET",
        candidate_config=_load_json(
            Path("evaluation/compat/experiments/candidates/cand-e06b-b3-specialized.template.json")
        ),
        evaluation_item=_load_json(FIXTURE_DIR / "evaluation-item.json"),
        model_input=_load_json(FIXTURE_DIR / "input.json"),
        gold=_load_json(FIXTURE_DIR / "gold.json"),
    )

    assert node["required_field_preservation_rate"] is not None
    assert node["required_field_preservation_rate"] < 1.0
    assert node["required_field_preservation_rate"] == 0.5


def test_controlled_replay_handoff_metrics_detect_evidence_id_loss(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest(tmp_path)
    runner = ControlledPostRetrievalReplayRunner(
        llm_runtime=FakeLLMRuntime(
            deque(
                [
                    _llm_result(_analysis_result()),
                    _llm_result(_answer_output_missing_evidence_ref()),
                    _llm_result(_review_output()),
                ]
            )
        ),
        manifest_path=manifest_path,
    )

    _, node = runner.run(
        experiment_id="EXP-E06B-CONTROLLED-POST-RET",
        candidate_config=_load_json(
            Path("evaluation/compat/experiments/candidates/cand-e06b-b3-specialized.template.json")
        ),
        evaluation_item=_load_json(FIXTURE_DIR / "evaluation-item.json"),
        model_input=_load_json(FIXTURE_DIR / "input.json"),
        gold=_load_json(FIXTURE_DIR / "gold.json"),
    )

    assert node["required_field_preservation_rate"] is not None
    assert node["evidence_id_preservation_rate"] is not None
    assert node["required_field_preservation_rate"] < 1.0
    assert node["evidence_id_preservation_rate"] < 1.0
    assert node["evidence_id_preservation_rate"] == 0.0
    assert node["constraint_loss_count"] >= 1


def test_controlled_replay_handoff_metrics_detect_answer_type_constraint_loss(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest(tmp_path)
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
    gold = _load_json(FIXTURE_DIR / "gold.json")
    _nested_mapping(gold, "gold")["expected_answer_type"] = "PLAN"

    _, node = runner.run(
        experiment_id="EXP-E06B-CONTROLLED-POST-RET",
        candidate_config=_load_json(
            Path("evaluation/compat/experiments/candidates/cand-e06b-b1-integrated.template.json")
        ),
        evaluation_item=_load_json(FIXTURE_DIR / "evaluation-item.json"),
        model_input=_load_json(FIXTURE_DIR / "input.json"),
        gold=gold,
    )

    assert node["constraint_loss_count"] > 0
    assert node["contradiction_introduced"] is False


def test_fixed_environment_payload_is_identical_for_b1_b2_b3_except_independent_variable() -> None:
    evaluation_item = _load_json(FIXTURE_DIR / "evaluation-item.json")
    fixture_snapshot_id = "FW-D-001"
    b1 = _build_fixed_environment_payload(
        candidate_config=_load_json(
            Path("evaluation/compat/experiments/candidates/cand-e06b-b1-integrated.template.json")
        ),
        evaluation_item=evaluation_item,
        fixture_snapshot_id=fixture_snapshot_id,
    )
    b2 = _build_fixed_environment_payload(
        candidate_config=_load_json(
            Path("evaluation/compat/experiments/candidates/cand-e06b-b2-staged.template.json")
        ),
        evaluation_item=evaluation_item,
        fixture_snapshot_id=fixture_snapshot_id,
    )
    b3 = _build_fixed_environment_payload(
        candidate_config=_load_json(
            Path("evaluation/compat/experiments/candidates/cand-e06b-b3-specialized.template.json")
        ),
        evaluation_item=evaluation_item,
        fixture_snapshot_id=fixture_snapshot_id,
    )

    assert b1 == b2
    assert b2 == b3


def test_fixed_environment_payload_is_identical_for_e06a_profiles_except_independent_variable() -> (
    None
):
    evaluation_item = _load_json(FIXTURE_DIR / "evaluation-item.json")
    fixture_snapshot_id = "FW-D-001"
    single = _build_fixed_environment_payload(
        candidate_config=_load_json(
            Path("evaluation/compat/experiments/candidates/cand-e06-single.template.json")
        ),
        evaluation_item=evaluation_item,
        fixture_snapshot_id=fixture_snapshot_id,
    )
    three = _build_fixed_environment_payload(
        candidate_config=_load_json(
            Path("evaluation/compat/experiments/candidates/cand-e06-three.template.json")
        ),
        evaluation_item=evaluation_item,
        fixture_snapshot_id=fixture_snapshot_id,
    )
    six = _build_fixed_environment_payload(
        candidate_config=_load_json(
            Path("evaluation/compat/experiments/candidates/cand-e06-six.template.json")
        ),
        evaluation_item=evaluation_item,
        fixture_snapshot_id=fixture_snapshot_id,
    )

    assert single == three
    assert three == six


def _load_json(path: Path) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise AssertionError(f"expected JSON object: {path}")
    return cast(dict[str, object], value)


def _nested_mapping(payload: Mapping[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict) or not all(isinstance(item, str) for item in value):
        raise AssertionError(f"{key} must be an object with string keys")
    return cast(dict[str, object], value)


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
        "schema_version": 2,
        "status": "PLAN_READY",
        "plan_id": "plan-1",
        "summary": "Read the authoritative Gmail thread only.",
        "objective": "Use the frozen Gmail evidence without other products.",
        "actions": [
            {
                "schema_version": 2,
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
    actions = payload.get("actions")
    if not isinstance(actions, list) or not actions or not isinstance(actions[0], dict):
        raise AssertionError("plan actions must contain an object")
    action = cast(dict[str, object], actions[0])
    action["tool_name"] = "gmail_send"
    action["effect"] = "SEND"
    return payload


def _answer_output_missing_resource_ref() -> dict[str, object]:
    payload = _answer_output()
    payload["resource_refs"] = []
    return payload


def _answer_output_missing_evidence_ref() -> dict[str, object]:
    payload = _answer_output()
    payload["evidence_refs"] = []
    return payload


def _set_nested_value(payload: dict[str, object], field_path: str, value: object) -> None:
    path = field_path.split(".")
    cursor: dict[str, object] = payload
    for key in path[:-1]:
        next_value = cursor[key]
        if not isinstance(next_value, dict) or not all(
            isinstance(item, str) for item in next_value
        ):
            raise AssertionError(f"non-dict path segment: {field_path}")
        cursor = cast(dict[str, object], next_value)
    cursor[path[-1]] = value


def _review_output() -> dict[str, object]:
    return {
        "schema_version": 2,
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
            "schema_version": 2,
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
            "schema_version": 2,
            "status": "PLAN_READY",
            "answer_draft": None,
            "plan_draft": _plan_output(),
        },
    }
