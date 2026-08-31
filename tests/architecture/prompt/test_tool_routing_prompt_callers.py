from __future__ import annotations

import ast
from pathlib import Path

from google_work_agent.application.prompt_runtime.contracts.prompt_runtime_input_contract import (
    REQUIRED_PROMPT_SLOT_IDS,
)
from google_work_agent.application.prompt_runtime.load_prompt_input_contract import (
    load_prompt_input_contract,
)

ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = ROOT / "src/google_work_agent"
TOOL_ROUTING_OWNER = SOURCE_ROOT / "application/agents/tool_routing"
TOOL_ROUTING_GRAPH = SOURCE_ROOT / "adapters/langgraph/subgraphs/tool_routing/graph.py"
SINGLE_PROFILE = SOURCE_ROOT / "adapters/langgraph/subgraphs/single_workflow.py"
THREE_STAGE_PROFILE = SOURCE_ROOT / "adapters/langgraph/subgraphs/three_stage.py"
CANONICAL_TOOL_ROUTING_PROMPTS = {
    "tool_routing.determine_io_resources",
    "tool_routing.select_tool_if_needed",
}
PREDECESSOR_PROMPTS = {
    "tool_route.determine_io_resources",
    "tool_route.determine_io_resources.revise",
    "tool_route.select_tool_if_needed",
    "tool_route.select_tool_if_needed.revise",
}


def _string_constants(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _loaded_prompt_ids(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    loaded: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function_name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else None
        )
        first = node.args[0]
        if (
            function_name == "load_prompt_reference"
            and isinstance(first, ast.Constant)
            and isinstance(first.value, str)
            and first.value.startswith(("tool_route.", "tool_routing."))
        ):
            loaded.add(first.value)
    return loaded


def test_tool_routing_product_prompt_callers_use_only_canonical_slots() -> None:
    loaded = set()
    production_constants = set()
    for path in SOURCE_ROOT.rglob("*.py"):
        loaded.update(_loaded_prompt_ids(path))
        production_constants.update(_string_constants(path))

    assert loaded == CANONICAL_TOOL_ROUTING_PROMPTS
    assert loaded <= REQUIRED_PROMPT_SLOT_IDS
    assert not PREDECESSOR_PROMPTS & production_constants
    assert (
        not {f"{prompt_id}.revise" for prompt_id in CANONICAL_TOOL_ROUTING_PROMPTS}
        & production_constants
    )


def test_tool_routing_prompt_inputs_match_current_runtime_contract() -> None:
    contract = load_prompt_input_contract()
    determine = contract.entry("tool_routing.determine_io_resources")
    select = contract.entry("tool_routing.select_tool_if_needed")

    assert determine.required_root_fields == (
        "request_intent",
        "eligible_route_capabilities",
    )
    assert determine.optional_root_fields == ("confirmation_response",)
    assert select.required_root_fields == (
        "route_candidate",
        "registered_candidates",
    )
    assert select.optional_root_fields == ("confirmation_response",)


def test_tool_routing_graph_has_no_separate_revision_prompt_authority() -> None:
    source = TOOL_ROUTING_GRAPH.read_text(encoding="utf-8")
    owner_source = "\n".join(
        path.read_text(encoding="utf-8") for path in TOOL_ROUTING_OWNER.rglob("*.py")
    )

    assert "revision_prompt_ref" not in source
    assert "revision_prompt_ref" not in owner_source
    assert ".revise" not in source
    assert ".revise" not in owner_source


def test_profile_composition_has_no_product_prompt_authority() -> None:
    profile_source = "\n".join(
        path.read_text(encoding="utf-8") for path in (SINGLE_PROFILE, THREE_STAGE_PROFILE)
    )

    assert "load_prompt_reference" not in profile_source
    assert "invoke_structured" not in profile_source
    assert "StructuredLLMRuntime" not in profile_source
    assert "PromptRef" not in profile_source
    assert "profile.single" not in profile_source
    assert "profile.three" not in profile_source
