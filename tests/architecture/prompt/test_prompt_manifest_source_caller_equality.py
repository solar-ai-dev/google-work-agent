from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import cast

from google_work_agent.application.prompt_runtime.contracts.prompt_runtime_input_contract import (
    REQUIRED_PROMPT_RUNTIME_NODE_BY_SLOT,
    REQUIRED_PROMPT_SLOT_IDS,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
)

ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = ROOT / "src" / "google_work_agent"
PROMPT_RUNTIME = SOURCE_ROOT / "application" / "prompt_runtime"
DETERMINISTIC_OPERATIONS = (
    "application/agents/request_understanding/finalize_intent.py",
    "application/agents/request_understanding/validate_intent.py",
    "application/agents/tool_routing/resolve_policy_preconditions.py",
    "application/agents/tool_routing/bind_registry_candidates.py",
    "application/agents/tool_routing/finalize_route.py",
    "application/agents/tool_routing/validate_route.py",
    "application/agents/retrieval/build_query.py",
    "application/agents/retrieval/execute_read.py",
    "application/agents/retrieval/normalize_segments.py",
    "application/agents/retrieval/resolve_availability.py",
    "application/agents/retrieval/rag_retrieve_rerank.py",
    "application/agents/retrieval/finalize_retrieval.py",
    "application/agents/work_analysis/validate_relations.py",
    "application/agents/work_analysis/assemble_work_analysis.py",
    "application/agents/work_analysis/validate_work_analysis.py",
    "application/agents/planning/choose_answer_or_action_from_route.py",
    "application/agents/planning/resolve_default_container.py",
    "application/agents/planning/build_dependencies.py",
    "application/agents/planning/assemble_plan.py",
    "application/agents/planning/validate_plan.py",
    "application/agents/review/aggregate_review_findings.py",
    "application/agents/review/validate_review.py",
)


def _manifest_slots() -> list[dict[str, object]]:
    payload = cast(
        dict[str, object],
        json.loads(default_prompt_manifest_path().read_text(encoding="utf-8")),
    )
    return cast(list[dict[str, object]], payload["slots"])


def test_canonical_prompt_manifest__source_and_caller__contract_sets_are_equal() -> None:
    slots = _manifest_slots()
    manifest_ids = {cast(str, slot["prompt_slot_id"]) for slot in slots}
    prompt_ids = {cast(str, slot["prompt_id"]) for slot in slots}
    runtime_callers = {cast(str, slot["runtime_node_id"]) for slot in slots}
    sources = {path.stem for path in (PROMPT_RUNTIME / "sources").glob("*.md")}

    assert len(slots) == 21
    assert manifest_ids == prompt_ids == sources == REQUIRED_PROMPT_SLOT_IDS
    assert runtime_callers == set(REQUIRED_PROMPT_RUNTIME_NODE_BY_SLOT.values())


def test_broad_predecessor__sources_are_absent__from_canonical_runtime() -> None:
    source_ids = {path.stem for path in (PROMPT_RUNTIME / "sources").glob("*.md")}

    assert "work_analysis.resolve_relations" not in source_ids
    assert "review.inspect" not in source_ids
    assert "review.recheck" not in source_ids


def test_all_22__deterministic_operations_are__product_prompt_free() -> None:
    banned_names = {
        "PROMPT_ID",
        "PromptReference",
        "PromptRegistry",
        "assemble_prompt",
        "load_prompt_reference",
        "invoke_structured",
    }
    for relative_path in DETERMINISTIC_OPERATIONS:
        path = SOURCE_ROOT / relative_path
        if not path.is_file():
            # File creation/caller cut-over belongs to the successor Agent slices.
            # The #110 foundation gate only prevents a Product Prompt authority
            # from being assigned to any deterministic responsibility.
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        observed = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        assert banned_names.isdisjoint(observed), relative_path

    deterministic_prompt_ids = {
        f"{Path(relative_path).parent.name}.{Path(relative_path).stem}"
        for relative_path in DETERMINISTIC_OPERATIONS
    }
    assert deterministic_prompt_ids.isdisjoint(REQUIRED_PROMPT_SLOT_IDS)


def test_prompt_registry__and_assembler_have__one_production_authority() -> None:
    registry_classes: list[Path] = []
    assembler_functions: list[Path] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "PromptRegistry":
                registry_classes.append(path)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == (
                "assemble_prompt"
            ):
                assembler_functions.append(path)

    assert registry_classes == [PROMPT_RUNTIME / "prompt_registry.py"]
    assert assembler_functions == [PROMPT_RUNTIME / "assemble_prompt.py"]
    assert not (SOURCE_ROOT / "application/orchestration/prompt_registry.py").exists()
    assert not (SOURCE_ROOT / "application/orchestration/prompt_input_contract.py").exists()


def test_production_provider__dispatch_uses_the__canonical_prompt_assembler() -> None:
    composition = (SOURCE_ROOT / "api/composition.py").read_text(encoding="utf-8")
    gemini = (SOURCE_ROOT / "adapters/llm/gemini/structured_inference.py").read_text(
        encoding="utf-8"
    )
    ollama = (SOURCE_ROOT / "adapters/llm/ollama/transport.py").read_text(encoding="utf-8")

    assert composition.count("assemble_instruction_text=lambda prompt_ref, prompt_input") == 2
    assert (
        composition.count(
            "assemble_prompt(\n                prompt_ref, prompt_input, registry=prompt_registry"
        )
        == 2
    )
    assert "resolve_instruction_text" not in composition
    for provider_source in (gemini, ollama):
        assert "self.assemble_instruction_text(prompt_ref, prompt_input)" in provider_source
        assert "resolve_instruction_text" not in provider_source
