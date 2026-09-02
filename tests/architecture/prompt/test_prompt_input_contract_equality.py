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


def test_prompt_input_contract__manifest_and_sources__are_exact_set_equal() -> None:
    registry = PromptRegistry()
    contract = load_prompt_input_contract()

    assert registry.slot_ids == contract.slot_ids == REQUIRED_PROMPT_SLOT_IDS


def test_prompt_input__contract_has__one_loader_authority() -> None:
    loaders: list[Path] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == (
                "load_prompt_input_contract"
            ):
                loaders.append(path)

    assert loaders == [SOURCE_ROOT / "application/prompt_runtime/load_prompt_input_contract.py"]


def test_forbidden_product__prompt_input__families_are_closed() -> None:
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


def test_retrieval_followup_projection__matches_the_canonical__plural_attempt_field() -> None:
    entry = load_prompt_input_contract().entry("retrieval.plan_query")

    assert "prior_query_attempts" in entry.optional_root_fields
    assert "prior_query_attempt" not in entry.optional_root_fields
