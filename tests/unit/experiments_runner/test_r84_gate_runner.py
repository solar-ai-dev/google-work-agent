"""Unit tests for experiments/runner/r84_gate_runner.py's SCHEMA_REPAIR lane,
Gate Result Ledger, and explicit Activation separation.

experiments/runner/ is not an importable package (pythonpath is ["src"]
only, per pyproject.toml) -- this file inserts it onto sys.path itself,
mirroring how the script and its own diagnostic tooling already do this.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT / "experiments" / "runner") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "experiments" / "runner"))

import pytest  # noqa: E402
import r84_gate_runner as gate_runner  # noqa: E402
from tests.support.fakes import FakeOllamaTransport  # noqa: E402

from google_work_agent.adapters.llm.ollama import OllamaStructuredLLMProvider  # noqa: E402
from google_work_agent.application.llm import LLMRuntimeService, NullLLMEventRecorder  # noqa: E402
from google_work_agent.application.workflows.context_retrieval import (  # noqa: E402
    EVIDENCE_SELECTION_OUTPUT_SCHEMA,
)
from google_work_agent.ports import (  # noqa: E402
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
)

VALID_EVIDENCE_OUTPUT = {
    "schema_version": 1,
    "result": "SELECTED",
    "selected_segment_ids": ["SEG-1", "SEG-2"],
    "evidence_drafts": [
        {
            "schema_version": 1,
            "evidence_id": "EV-1",
            "resource_handle": "RES-1",
            "segment_id": "SEG-1",
            "kind": "EMAIL",
            "excerpt": "excerpt text",
            "locator": None,
            "reason_codes": [],
        }
    ],
    "excluded_resource_handles": [],
    "missing_information": [],
    "ambiguity": None,
}


def _prompt_ref(prompt_id: str) -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test-bundle",
        prompt_id=prompt_id,
        prompt_version="1",
        content_hash="hash-" + prompt_id,
        agent_role="context_retriever",
        subgraph_name="context_retriever",
        node_name=prompt_id.split(".")[-1],
        node_state="TEST",
        purpose="test",
        input_schema_version="v1",
        output_schema_version="v1",
    )


def _service_with_provider(
    transport: FakeOllamaTransport,
) -> tuple[OllamaStructuredLLMProvider, LLMRuntimeService]:
    provider = OllamaStructuredLLMProvider(
        provider_name="ollama",
        transport=transport,
        endpoint="http://127.0.0.1:11434",
        model_id="qwen2.5:3b",
    )
    service = LLMRuntimeService(
        settings_service=lambda: (_ for _ in ()).throw(RuntimeError("unused")),
        status_service=None,  # type: ignore[arg-type]
        credential_service=None,  # type: ignore[arg-type]
        api_provider=None,  # type: ignore[arg-type]
        ollama_provider_factory=lambda model, settings: provider,
        router=None,  # type: ignore[arg-type]
        runtime_policy=RuntimePolicy(local_timeout_seconds=30),
        event_recorder=NullLLMEventRecorder(),
    )
    return provider, service


def _payload(content: object) -> ProviderResponsePayload:
    return ProviderResponsePayload(
        content=content,
        model="qwen2.5:3b",
        provider_request_id=None,
        input_tokens=1,
        output_tokens=1,
        latency_ms=1,
    )


# ---------------------------------------------------------------------------
# Mutation determinism and correctness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation",
    gate_runner.SCHEMA_MUTATIONS,
    ids=[m.category for m in gate_runner.SCHEMA_MUTATIONS],
)
def test_mutation_breaks_the_real_schema_but_seed_stays_valid(mutation: object) -> None:
    import jsonschema

    seed = dict(VALID_EVIDENCE_OUTPUT)
    jsonschema.validate(instance=seed, schema=dict(EVIDENCE_SELECTION_OUTPUT_SCHEMA.json_schema))

    mutated, changed_fields = mutation.apply(seed)  # type: ignore[attr-defined]
    assert changed_fields, "every mutation must declare which field it corrupted"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            instance=mutated, schema=dict(EVIDENCE_SELECTION_OUTPUT_SCHEMA.json_schema)
        )


def test_mutation_is_deterministic() -> None:
    for mutation in gate_runner.SCHEMA_MUTATIONS:
        first = mutation.apply(dict(VALID_EVIDENCE_OUTPUT))
        second = mutation.apply(dict(VALID_EVIDENCE_OUTPUT))
        assert first == second, f"{mutation.category} mutation must be deterministic"


def test_six_categories_match_docs_15_schema_repair_taxonomy() -> None:
    categories = {m.category for m in gate_runner.SCHEMA_MUTATIONS}
    assert categories == gate_runner.SCHEMA_REPAIR_CATEGORIES


# ---------------------------------------------------------------------------
# INITIAL lane must never run or count SCHEMA_REPAIR categories
# ---------------------------------------------------------------------------


def test_run_slot_excludes_schema_repair_categories_from_coverage_and_never_dispatches() -> None:
    only_schema_categories = {
        "SCHEMA_INVALID_ENUM": [
            gate_runner.DatasetItem("x1", "context.select_evidence", "SCHEMA_INVALID_ENUM", {}),
            gate_runner.DatasetItem("x2", "context.select_evidence", "SCHEMA_INVALID_ENUM", {}),
            gate_runner.DatasetItem("x3", "context.select_evidence", "SCHEMA_INVALID_ENUM", {}),
        ]
    }
    transport = FakeOllamaTransport()  # no queued payloads: dispatch would raise IndexError
    provider, service = _service_with_provider(transport)

    report = gate_runner.run_slot(
        provider,
        service,
        "context.select_evidence",
        dev_groups=only_schema_categories,
        holdout_groups=only_schema_categories,
        limit=None,
        run_index=0,
    )

    assert report.group_results == {}
    assert report.insufficient_coverage == []
    assert len(transport.invocations) == 0


# ---------------------------------------------------------------------------
# SCHEMA_REPAIR lane grading
# ---------------------------------------------------------------------------


def test_repair_case_passes_when_repair_restores_exact_original() -> None:
    transport = FakeOllamaTransport()
    transport.queued_payloads.append(_payload(VALID_EVIDENCE_OUTPUT))  # seed call
    transport.queued_payloads.append(_payload(VALID_EVIDENCE_OUTPUT))  # repair restores it exactly
    provider, service = _service_with_provider(transport)
    mutation = next(m for m in gate_runner.SCHEMA_MUTATIONS if m.category == "SCHEMA_INVALID_ENUM")
    seed_item = gate_runner.DatasetItem(
        "seed-1", "context.select_evidence", "NORMAL", {"goal": "x"}
    )

    result = gate_runner._run_repair_case(
        provider,
        service,
        _prompt_ref("context.select_evidence"),
        _prompt_ref("context.repair"),
        seed_item=seed_item,
        mutation=mutation,
        run_id="test-1",
    )

    assert result.passed is True
    assert result.repair_schema_pass is True
    assert result.semantic_pass is True
    assert result.repair_attempt_count == 1
    # the repair call must have received the real ContextRepairInputV1 shape
    repair_call = transport.invocations[1]
    sent_input = repair_call["prompt_input"]
    assert set(sent_input) == {
        "schema_version",
        "original_input",
        "previous_output",
        "failure_record",
        "validator_errors",
        "changed_fields_allowed",
        "attempt_no",
        "max_attempts",
    }
    assert sent_input["failure_record"]["failure_reason_code"] == "SCHEMA_INVALID_ENUM"
    assert sent_input["changed_fields_allowed"] == ["result"]
    assert sent_input["original_input"] == seed_item.prompt_input


def test_repair_case_fails_when_repair_changes_an_unrelated_field() -> None:
    transport = FakeOllamaTransport()
    transport.queued_payloads.append(_payload(VALID_EVIDENCE_OUTPUT))  # seed
    drifted = dict(VALID_EVIDENCE_OUTPUT)
    drifted["selected_segment_ids"] = ["SEG-1"]  # dropped SEG-2: an unrelated semantic change
    transport.queued_payloads.append(_payload(drifted))  # repair drifts
    provider, service = _service_with_provider(transport)
    mutation = next(m for m in gate_runner.SCHEMA_MUTATIONS if m.category == "SCHEMA_INVALID_ENUM")
    seed_item = gate_runner.DatasetItem(
        "seed-1", "context.select_evidence", "NORMAL", {"goal": "x"}
    )

    result = gate_runner._run_repair_case(
        provider,
        service,
        _prompt_ref("context.select_evidence"),
        _prompt_ref("context.repair"),
        seed_item=seed_item,
        mutation=mutation,
        run_id="test-2",
    )

    assert result.passed is False
    assert result.repair_schema_pass is True  # still schema-valid JSON
    assert result.semantic_pass is False  # but meaning drifted outside the injected failure


def test_repair_case_fails_when_repaired_output_is_still_schema_invalid() -> None:
    transport = FakeOllamaTransport()
    transport.queued_payloads.append(_payload(VALID_EVIDENCE_OUTPUT))  # seed
    still_broken = dict(VALID_EVIDENCE_OUTPUT)
    still_broken["result"] = "COMPLETE"  # the model failed to actually repair it
    transport.queued_payloads.append(_payload(still_broken))
    provider, service = _service_with_provider(transport)
    mutation = next(m for m in gate_runner.SCHEMA_MUTATIONS if m.category == "SCHEMA_INVALID_ENUM")
    seed_item = gate_runner.DatasetItem(
        "seed-1", "context.select_evidence", "NORMAL", {"goal": "x"}
    )

    result = gate_runner._run_repair_case(
        provider,
        service,
        _prompt_ref("context.select_evidence"),
        _prompt_ref("context.repair"),
        seed_item=seed_item,
        mutation=mutation,
        run_id="test-3",
    )

    assert result.passed is False
    assert result.repair_schema_pass is False
    assert "repair invoke raised" in result.detail


def test_repair_case_rejects_a_seed_that_is_already_invalid() -> None:
    transport = FakeOllamaTransport()
    broken_seed = dict(VALID_EVIDENCE_OUTPUT)
    broken_seed["result"] = "NOT_A_REAL_ENUM_VALUE"
    transport.queued_payloads.append(_payload(broken_seed))
    provider, service = _service_with_provider(transport)
    mutation = next(m for m in gate_runner.SCHEMA_MUTATIONS if m.category == "SCHEMA_WRONG_TYPE")
    seed_item = gate_runner.DatasetItem(
        "seed-1", "context.select_evidence", "NORMAL", {"goal": "x"}
    )

    result = gate_runner._run_repair_case(
        provider,
        service,
        _prompt_ref("context.select_evidence"),
        _prompt_ref("context.repair"),
        seed_item=seed_item,
        mutation=mutation,
        run_id="test-4",
    )

    assert result.passed is False
    assert result.initial_schema_pass is False
    # must never have reached the repair call at all
    assert len(transport.invocations) == 1


def test_repair_is_never_retried_more_than_once() -> None:
    """docs/15 section 8.1: Schema Repair is Node Call max 1 attempt."""
    transport = FakeOllamaTransport()
    transport.queued_payloads.append(_payload(VALID_EVIDENCE_OUTPUT))
    still_broken = dict(VALID_EVIDENCE_OUTPUT)
    still_broken["result"] = "COMPLETE"
    transport.queued_payloads.append(_payload(still_broken))
    provider, service = _service_with_provider(transport)
    mutation = next(m for m in gate_runner.SCHEMA_MUTATIONS if m.category == "SCHEMA_INVALID_ENUM")
    seed_item = gate_runner.DatasetItem(
        "seed-1", "context.select_evidence", "NORMAL", {"goal": "x"}
    )

    gate_runner._run_repair_case(
        provider,
        service,
        _prompt_ref("context.select_evidence"),
        _prompt_ref("context.repair"),
        seed_item=seed_item,
        mutation=mutation,
        run_id="test-5",
    )

    # exactly seed(1) + repair(1) = 2 calls total, no second repair attempt
    assert len(transport.invocations) == 2


# ---------------------------------------------------------------------------
# Gate Result Ledger: lane/retry_kind fields and item-level detail
# ---------------------------------------------------------------------------


def test_ledger_record_marks_initial_lane_correctly() -> None:
    report = gate_runner.SlotReport(
        target_node_id="acquisition.plan_sources",
        group_results={
            "NORMAL": (
                [gate_runner.ItemResult(item_id="i1", passed=True, detail="ok")],
                [gate_runner.ItemResult(item_id="i2", passed=True, detail="ok")],
            )
        },
        safety_results=[],
        insufficient_coverage=[],
        prompt_ref=_prompt_ref("acquisition.plan_sources"),
    )

    record = gate_runner._build_gate_result_record(
        report,
        gate_run_id="run-1",
        provider="ollama",
        model_id="qwen2.5:3b",
        evaluated_at="2026-08-10T00:00:00Z",
    )

    assert record["evaluation_lane"] == "INITIAL"
    assert record["retry_kind"] == "NONE"
    assert record["passed"] is True
    assert len(record["item_results"]) == 2


def test_ledger_record_marks_schema_repair_lane_correctly() -> None:
    report = gate_runner.SlotReport(
        target_node_id=gate_runner.CONTEXT_REPAIR_TARGET_NODE_ID,
        group_results={
            "SCHEMA_INVALID_ENUM": (
                [
                    gate_runner.RepairItemResult(
                        item_id="i1",
                        passed=True,
                        detail="ok",
                        repair_schema_pass=True,
                        semantic_pass=True,
                        repair_attempt_count=1,
                    )
                ],
                [
                    gate_runner.RepairItemResult(
                        item_id="i2",
                        passed=True,
                        detail="ok",
                        repair_schema_pass=True,
                        semantic_pass=True,
                        repair_attempt_count=1,
                    )
                ],
            )
        },
        safety_results=[],
        insufficient_coverage=[],
        prompt_ref=_prompt_ref("context.repair"),
    )

    record = gate_runner._build_gate_result_record(
        report,
        gate_run_id="run-1",
        provider="ollama",
        model_id="qwen2.5:3b",
        evaluated_at="2026-08-10T00:00:00Z",
    )

    assert record["evaluation_lane"] == "SCHEMA_REPAIR"
    assert record["retry_kind"] == "SCHEMA_REPAIR"
    assert record["item_results"][0]["repair_schema_pass"] is True
    assert record["item_results"][0]["semantic_pass"] is True


# ---------------------------------------------------------------------------
# Gate Result vs Activation separation (also covered by live manual testing
# in the turn's own report; these pin the behavior permanently)
# ---------------------------------------------------------------------------


def _write_test_manifest(tmp_path: Path, *, activation_status: str = "DRAFT") -> Path:
    manifest_path = tmp_path / "prompt-manifest-v0.8.3.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "prompt_bundle_version": "test",
                "slots": [
                    {"slot_id": "acquisition.plan_sources", "activation_status": activation_status},
                    {"slot_id": "review.inspect", "activation_status": "RUNTIME_ACTIVE"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def _write_test_ledger(tmp_path: Path, *, slot_id: str, passed: bool) -> Path:
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(
        json.dumps(
            {
                "gate_run_id": "run-x",
                "results": [
                    {
                        "gate_run_id": "run-x",
                        "slot_id": slot_id,
                        "provider": "ollama",
                        "model_id": "qwen2.5:3b",
                        "passed": passed,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return ledger_path


def test_activate_refuses_a_failed_slot(tmp_path: Path) -> None:
    manifest_path = _write_test_manifest(tmp_path)
    before = manifest_path.read_text(encoding="utf-8")
    ledger_path = _write_test_ledger(tmp_path, slot_id="acquisition.plan_sources", passed=False)

    with pytest.raises(SystemExit, match="did not pass"):
        gate_runner._activate_slot(manifest_path, ledger_path, {"acquisition.plan_sources"})

    assert manifest_path.read_text(encoding="utf-8") == before


def test_activate_refuses_a_slot_missing_from_the_ledger(tmp_path: Path) -> None:
    manifest_path = _write_test_manifest(tmp_path)
    ledger_path = _write_test_ledger(tmp_path, slot_id="some.other.slot", passed=True)

    with pytest.raises(SystemExit, match="no record"):
        gate_runner._activate_slot(manifest_path, ledger_path, {"acquisition.plan_sources"})


def test_activate_promotes_only_the_named_slot_and_preserves_the_rest(tmp_path: Path) -> None:
    manifest_path = _write_test_manifest(tmp_path)
    before = json.loads(manifest_path.read_text(encoding="utf-8"))
    ledger_path = _write_test_ledger(tmp_path, slot_id="acquisition.plan_sources", passed=True)

    gate_runner._activate_slot(manifest_path, ledger_path, {"acquisition.plan_sources"})

    after = json.loads(manifest_path.read_text(encoding="utf-8"))
    promoted = next(s for s in after["slots"] if s["slot_id"] == "acquisition.plan_sources")
    untouched = next(s for s in after["slots"] if s["slot_id"] == "review.inspect")
    assert promoted["activation_status"] == "RUNTIME_ACTIVE"
    assert promoted["activated_from_gate_result"]["gate_run_id"] == "run-x"
    assert untouched == next(s for s in before["slots"] if s["slot_id"] == "review.inspect")
