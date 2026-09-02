from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import cast

from tests.support.production_runtime import build_test_production_container

from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    SessionMemorySecretStore,
)
from google_work_agent.application.prompt_runtime.contracts.prompt_runtime_input_contract import (
    REQUIRED_PROMPT_SLOT_IDS,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
)
from google_work_agent.ports.system.readiness_port import ReadinessState

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src/google_work_agent"


def test_pre_experiment_manifest__has_zero_unsupported__activation_claims() -> None:
    payload = cast(
        dict[str, object],
        json.loads(default_prompt_manifest_path().read_text(encoding="utf-8")),
    )
    slots = cast(list[dict[str, object]], payload["slots"])

    assert {str(slot["prompt_slot_id"]) for slot in slots} == REQUIRED_PROMPT_SLOT_IDS
    assert len(slots) == 21
    assert all(slot["activation_status"] == "DRAFT" for slot in slots)
    assert all(
        slot[field] is False
        for slot in slots
        for field in (
            "node_dev_pass",
            "node_holdout_pass",
            "safety_gate_pass",
            "manifest_approved",
        )
    )
    assert all(slot["activation_evidence"] is None for slot in slots)


def test_signed_prompt_scope__has_zero_ambient__environment_override() -> None:
    composition = (SOURCE_ROOT / "api/composition.py").read_text(encoding="utf-8")
    registry = (SOURCE_ROOT / "application/prompt_runtime/prompt_registry.py").read_text(
        encoding="utf-8"
    )
    trees = (ast.parse(composition), ast.parse(registry))

    assert "PRODUCT_RELEASE" in composition
    assert "SIGNED_RELEASE_MANIFEST" in composition
    assert "GWA_PROMPT" not in composition
    assert "GWA_PROMPT" not in registry
    assert all(
        not (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and node.attr in {"getenv", "environ"}
        )
        for tree in trees
        for node in ast.walk(tree)
    )


def test_explicit_development_composition__reports_unvalidated_baseline__as_ready(
    tmp_path: Path,
) -> None:
    container = build_test_production_container(
        runtime_root=tmp_path / "runtime",
        mcp_module_name="tests.fakes.mcp_server",
        keyring_store=SessionMemorySecretStore(),
    )
    try:
        report = container.readiness_aggregator.evaluate()
        prompt_check = next(check for check in report.checks if check.name == "prompt_activation")

        assert report.state is ReadinessState.READY
        assert prompt_check.state is ReadinessState.READY
        assert prompt_check.detail == "UNVALIDATED_BASELINE"
        assert container.workflow_runtime.__class__.__name__ == "LangGraphWorkflowRuntime"
    finally:
        for close in reversed(container.shutdown_callbacks):
            close()


def test_release_assembler__requires_product_release__prompt_gate() -> None:
    source = (ROOT / "release/assemble_application_bundle.py").read_text(encoding="utf-8")

    assert "_validated_product_release_prompt_registry(inputs.prompt_manifest)" in source
    assert "registry.require_product_release_ready()" in source
    assert "_materialize_prompt_bundle(" in source
