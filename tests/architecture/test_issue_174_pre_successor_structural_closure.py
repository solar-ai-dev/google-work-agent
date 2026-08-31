"""Always-on exact-set proof for the pre-successor structural closure."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "google_work_agent"
APPLICATION_USE_CASES = SRC / "application" / "use_cases"
LANGGRAPH = SRC / "adapters" / "langgraph"

CANONICAL_APPLICATION_OWNERS = {
    "action",
    "approval",
    "attachment",
    "backup",
    "claim",
    "component_circuit",
    "connection",
    "conversation",
    "diagnostic_bundle",
    "execution_attempt",
    "llm_credential",
    "message",
    "plan",
    "recovery",
    "resource",
    "resource_ref",
    "run",
    "runtime_mode",
    "runtime_status",
    "setting",
    "shutdown",
    "sse_event",
    "trace_event",
    "verification",
}

SEMANTIC_AUTHORITY_SUFFIXES = ("Handler", "Service", "Coordinator")

REMOVED_AUTHORITY_PATHS = {
    "application/use_cases/action/execute_read_action.py",
    "application/use_cases/action/write_preflight.py",
    "application/use_cases/execution_attempt/execution_phase.py",
    "application/use_cases/llm",
    "application/use_cases/plan/save_read_only_plan.py",
    "application/use_cases/plan/save_write_plan.py",
    "application/use_cases/run/coordinator_outcomes.py",
    "application/use_cases/run/get_execution_context.py",
    "application/use_cases/verification/normalize_snapshot.py",
}

REMOVED_AUTHORITY_SYMBOLS = {
    "ExecuteReadActionService",
    "FailRunService",
    "GetExecutionContextHandler",
    "LLMRuntimeService",
    "RunOutcomeHandler",
    "SaveReadOnlyPlanService",
    "SaveWritePlanService",
    "StructuredLLMRuntime",
    "WriteExecutionPhaseCoordinator",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _application_ledger_authorities() -> set[tuple[str, str]]:
    authorities: set[tuple[str, str]] = set()
    ledger = ROOT / "implementation-inventory" / "ledger.md"
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| CAP-APP-"):
            continue
        escaped = line.replace(r"\|", "<PIPE>")
        fields = [field.strip().replace("<PIPE>", "|") for field in escaped.split("|")[1:-1]]
        directory, filename, symbol_field = fields[8:11]
        owned_field = symbol_field.split(";", 1)[0]
        for symbol in owned_field.split("/"):
            symbol = symbol.strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", symbol) and symbol.endswith(
                SEMANTIC_AUTHORITY_SUFFIXES
            ):
                authorities.add((f"{directory}{filename}", symbol))
    return authorities


def _actual_application_authorities() -> set[tuple[str, str]]:
    authorities: set[tuple[str, str]] = set()
    for path in APPLICATION_USE_CASES.rglob("*.py"):
        relative = path.relative_to(SRC).as_posix()
        for node in _tree(path).body:
            if isinstance(node, ast.ClassDef) and node.name.endswith(SEMANTIC_AUTHORITY_SUFFIXES):
                authorities.add((relative, node.name))
    return authorities


def test_application_semantic_owner_set_is_exact() -> None:
    actual = {
        path.name
        for path in APPLICATION_USE_CASES.iterdir()
        if path.is_dir() and any(path.glob("*.py"))
    }
    assert actual == CANONICAL_APPLICATION_OWNERS


def test_application_public_semantic_authority_set_equals_the_formal_manifest() -> None:
    expected = _application_ledger_authorities()
    actual = _actual_application_authorities()
    assert len(expected) == 97
    assert actual == expected


def test_removed_application_authorities_have_no_path_symbol_or_production_caller() -> None:
    for relative in REMOVED_AUTHORITY_PATHS:
        path = SRC / relative
        if path.suffix == ".py":
            assert not path.exists()
        else:
            assert not any(path.rglob("*.py"))
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        tree = _tree(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in REMOVED_AUTHORITY_SYMBOLS:
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{node.id}")
            elif isinstance(node, ast.Attribute) and node.attr in REMOVED_AUTHORITY_SYMBOLS:
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{node.attr}")
    assert offenders == []


def test_langgraph_does_not_construct_application_semantic_authorities() -> None:
    authority_names = {symbol for _path, symbol in _application_ledger_authorities()}
    offenders: list[str] = []
    for path in LANGGRAPH.rglob("*.py"):
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else None
            )
            if name in authority_names:
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{name}")
    assert offenders == []


def test_langgraph_shared_state_contains_runtime_envelopes_only() -> None:
    path = LANGGRAPH / "subgraph_state.py"
    public_classes = {
        node.name
        for node in _tree(path).body
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
    }
    assert public_classes == {"AgentLocalStateV1", "AgentSubgraphInputEnvelope"}
    source = path.read_text(encoding="utf-8")
    for owner in (
        "RequestUnderstanding",
        "ToolRouting",
        "ContextRetrieval",
        "WorkAnalysis",
        "PlanningInputState",
        "ReviewInputState",
        "AcquisitionLocalState",
    ):
        assert owner not in source


def test_write_execution_driver_has_no_persistence_or_semantic_construction_authority() -> None:
    path = LANGGRAPH / "write_execution_driver.py"
    tree = _tree(path)
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(module.startswith("google_work_agent.ports.persistence") for module in imports)
    assert not any(
        module.startswith("google_work_agent.adapters.persistence") for module in imports
    )
    assert "unit_of_work" not in path.read_text(encoding="utf-8")


def test_production_composition_has_one_public_builder_and_one_external_caller() -> None:
    composition = SRC / "api" / "composition.py"
    public_builders = {
        node.name
        for node in _tree(composition).body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("build_")
    }
    assert public_builders == {"build_production_runtime"}

    callers: list[str] = []
    for path in SRC.rglob("*.py"):
        if path == composition:
            continue
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Call) and (
                (isinstance(node.func, ast.Name) and node.func.id == "build_production_runtime")
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "build_production_runtime"
                )
            ):
                callers.append(path.relative_to(SRC).as_posix())
    assert callers == ["api/app.py"]


def test_create_app_is_the_only_fastapi_assembly_authority() -> None:
    owners: list[str] = []
    for path in SRC.rglob("*.py"):
        if any(
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "create_app"
            for node in _tree(path).body
        ):
            owners.append(path.relative_to(SRC).as_posix())
    assert owners == ["api/app.py"]
