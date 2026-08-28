from __future__ import annotations

import ast
from pathlib import Path

from google_work_agent.application.prompt_runtime.contracts.prompt_runtime_input_contract import (
    REQUIRED_PROMPT_SLOT_IDS,
)
from google_work_agent.application.prompt_runtime.load_prompt_input_contract import (
    load_prompt_input_contract,
)
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry

ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = ROOT / "src" / "google_work_agent"


def test_prompt_input_contract_manifest_and_sources_are_exact_set_equal() -> None:
    registry = PromptRegistry()
    contract = load_prompt_input_contract()

    assert registry.slot_ids == contract.slot_ids == REQUIRED_PROMPT_SLOT_IDS


def test_prompt_input_contract_has_one_loader_authority() -> None:
    loaders: list[Path] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == (
                "load_prompt_input_contract"
            ):
                loaders.append(path)

    assert loaders == [SOURCE_ROOT / "application/prompt_runtime/load_prompt_input_contract.py"]


def test_forbidden_product_prompt_input_families_are_closed() -> None:
    forbidden = load_prompt_input_contract().forbidden_input_fields
    required = {
        "conversation_history",
        "previous_run_artifacts",
        "checkpoint_metadata",
        "raw_provider_payload",
        "provider_continuation",
        "next_page_token",
        "mcp_arguments",
        "gold",
        "grader",
        "expected_route",
        "evaluation_item_id",
    }

    assert required.issubset(forbidden)
