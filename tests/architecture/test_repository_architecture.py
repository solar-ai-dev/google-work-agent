from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "src" / "google_work_agent"
FINAL_CUTOVER = os.environ.get("GWA_ARCHITECTURE_FINAL_CUTOVER") == "1"

ARCHITECTURE_ROLE_FILENAMES = {"state.py", "graph.py", "model.py", "composition.py"}
FORBIDDEN_FILENAMES = {
    "runtime.py",
    "service.py",
    "manager.py",
    "processor.py",
    "engine.py",
    "handler.py",
    "helpers.py",
    "helper.py",
    "utils.py",
    "util.py",
    "common.py",
    "shared.py",
    "misc.py",
    "config.py",
    "errors.py",
    "routing.py",
}
FORBIDDEN_GENERATION_PATTERNS = (
    re.compile(r"^canonical_.*\.py$"),
    re.compile(r"^production_.*\.py$"),
    re.compile(r"^legacy_.*\.py$"),
    re.compile(r"^new_.*\.py$"),
    re.compile(r"^old_.*\.py$"),
    re.compile(r"^final_.*\.py$"),
    re.compile(r"^.*_v\d+\.py$"),
    re.compile(r"^.*_r\d+\.py$"),
)
PROVIDER_SDK_ROOTS = {
    "googleapiclient",
    "google_auth_oauthlib",
    "google.auth",
    "google.oauth2",
    "google.cloud",
}
DOMAIN_OWNERS = {
    "conversation",
    "message",
    "run",
    "plan",
    "action",
    "approval",
    "claim",
    "execution_attempt",
    "verification",
    "recovery",
    "resource_ref",
    "evidence",
    "command_receipt",
    "policy_confirmation_receipt",
}
AGENT_CAPABILITIES: dict[str, set[str]] = {
    "request_understanding": {
        "identify_goal",
        "detect_ambiguity",
        "finalize_intent",
        "validate_intent",
    },
    "tool_routing": {
        "determine_io_resources",
        "bind_registry_candidates",
        "select_tool_if_needed",
        "finalize_route",
        "validate_route",
    },
    "retrieval": {
        "plan_query",
        "build_query",
        "execute_read",
        "normalize_segments",
        "rag_retrieve_rerank",
        "select_evidence",
        "assess_sufficiency",
        "finalize_retrieval",
    },
    "work_analysis": {
        "extract_work_facts",
        "resolve_entity_relations",
        "resolve_temporal_dependencies",
        "detect_duplicate_conflict_candidates",
        "validate_relations",
        "assess_information_gaps",
        "assess_operational_risks",
        "assemble_work_analysis",
        "validate_work_analysis",
    },
    "planning": {
        "choose_answer_or_action_from_route",
        "outline_answer",
        "compose_answer",
        "draft_action_objective_per_output_route",
        "compose_arguments_per_output_route",
        "build_dependencies",
        "assemble_plan",
        "validate_plan",
    },
    "review": {
        "inspect_goal_and_evidence",
        "inspect_action_scope_and_route",
        "inspect_constraints_and_policy_summary",
        "aggregate_review_findings",
        "validate_review",
        "recheck_affected_dimensions",
    },
}


def _production_python_files() -> list[Path]:
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _package_parts(path: Path) -> tuple[str, ...]:
    return path.relative_to(PACKAGE_ROOT).parts


def _is_forbidden_filename(path: Path) -> bool:
    if path.name in ARCHITECTURE_ROLE_FILENAMES:
        return False
    if path.name in FORBIDDEN_FILENAMES:
        return True
    return any(pattern.fullmatch(path.name) for pattern in FORBIDDEN_GENERATION_PATTERNS)


def _is_canonical_target_file(path: Path) -> bool:
    parts = _package_parts(path)
    if not parts:
        return False

    if parts[0] == "domain" and len(parts) >= 3 and parts[1] in DOMAIN_OWNERS:
        return True
    if parts[:2] == ("application", "use_cases") and len(parts) >= 4:
        return True
    if parts[:2] == ("application", "agents") and len(parts) >= 4:
        return True
    if parts[:2] == ("ports", "persistence") and len(parts) == 3:
        return True
    if parts[:4] == ("adapters", "persistence", "sqlite", "repositories"):
        return True
    if parts[:2] == ("adapters", "connectors") and len(parts) >= 6:
        return True
    if parts[:2] == ("adapters", "langgraph") and len(parts) >= 4:
        return parts[2] == "main" or parts[2] == "subgraphs"
    if parts[:2] == ("api", "schemas") and len(parts) >= 4:
        return True
    if parts[:2] == ("api", "routes") and len(parts) == 3:
        return True
    if parts[:2] == ("api", "dependencies") and len(parts) == 3:
        return True
    return False


def _canonical_target_files() -> list[Path]:
    return [path for path in _production_python_files() if _is_canonical_target_file(path)]


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _defined_function_names(path: Path) -> set[str]:
    tree = _parse(path)
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _defined_class_names(path: Path) -> set[str]:
    tree = _parse(path)
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _module_parts(module: str) -> tuple[str, ...]:
    prefix = "google_work_agent."
    if module == "google_work_agent":
        return ()
    if module.startswith(prefix):
        return tuple(module[len(prefix) :].split("."))
    return ()


def _pascal(stem: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in stem.split("_") if part)


def _assert_no_violations(violations: list[str]) -> None:
    assert not violations, "\n" + "\n".join(f"- {item}" for item in violations)


def test_immediate_canonical_targets_use_closed_world_filenames() -> None:
    violations = [
        f"forbidden canonical filename: {_relative(path)}"
        for path in _canonical_target_files()
        if _is_forbidden_filename(path)
    ]
    _assert_no_violations(violations)


def test_immediate_domain_owner_and_operation_per_file_grammar() -> None:
    violations: list[str] = []
    domain_root = PACKAGE_ROOT / "domain"
    for owner in sorted(DOMAIN_OWNERS):
        owner_root = domain_root / owner
        if not owner_root.exists():
            continue
        for child in owner_root.iterdir():
            if child.name == "__pycache__":
                continue
            if child.is_dir() and child.name not in {"transitions", "guards"}:
                violations.append(f"unexpected domain owner directory: {_relative(child)}")
            if child.is_file() and child.suffix == ".py" and child.name not in {
                "__init__.py",
                "model.py",
            }:
                violations.append(f"unexpected domain owner module: {_relative(child)}")

        for folder, prefix in (("transitions", "transition_"), ("guards", "guard_")):
            operation_root = owner_root / folder
            if not operation_root.exists():
                continue
            for path in sorted(operation_root.glob("*.py")):
                if path.name == "__init__.py":
                    continue
                expected = f"{prefix}{path.stem}"
                if expected not in _defined_function_names(path):
                    violations.append(
                        f"{_relative(path)} must define top-level {expected}()"
                    )
    _assert_no_violations(violations)


def test_immediate_application_use_case_grammar() -> None:
    violations: list[str] = []
    root = PACKAGE_ROOT / "application" / "use_cases"
    if not root.exists():
        return
    for owner_root in sorted(path for path in root.iterdir() if path.is_dir()):
        for path in sorted(owner_root.glob("*.py")):
            if path.name == "__init__.py":
                continue
            if not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+\.py", path.name):
                violations.append(f"invalid use-case filename: {_relative(path)}")
                continue
            base = _pascal(path.stem)
            classes = _defined_class_names(path)
            required = {f"{base}Result", f"{base}Handler"}
            missing = required - classes
            if missing:
                violations.append(
                    f"{_relative(path)} missing classes: {', '.join(sorted(missing))}"
                )
            input_types = {f"{base}Command", f"{base}Query"} & classes
            if len(input_types) != 1:
                violations.append(
                    f"{_relative(path)} must define exactly one of "
                    f"{base}Command/{base}Query"
                )
    _assert_no_violations(violations)


def test_immediate_agent_atomic_responsibility_grammar() -> None:
    violations: list[str] = []
    root = PACKAGE_ROOT / "application" / "agents"
    if not root.exists():
        return
    unknown_roles = sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and path.name not in AGENT_CAPABILITIES
    )
    violations.extend(f"unknown agent semantic owner: {role}" for role in unknown_roles)

    for role, capabilities in AGENT_CAPABILITIES.items():
        role_root = root / role
        if not role_root.exists():
            continue
        for path in sorted(role_root.glob("*.py")):
            if path.name == "__init__.py":
                continue
            if path.stem not in capabilities:
                violations.append(f"unknown/broad agent capability: {_relative(path)}")
                continue
            if path.stem not in _defined_function_names(path):
                violations.append(
                    f"{_relative(path)} must define top-level {path.stem}()"
                )
    _assert_no_violations(violations)


def test_immediate_persistence_port_sqlite_mirror() -> None:
    violations: list[str] = []
    port_root = PACKAGE_ROOT / "ports" / "persistence"
    sqlite_root = PACKAGE_ROOT / "adapters" / "persistence" / "sqlite" / "repositories"
    port_files = (
        {
            path.name
            for path in port_root.glob("*_repository.py")
            if path.name != "__init__.py"
        }
        if port_root.exists()
        else set()
    )
    sqlite_files = (
        {
            path.name
            for path in sqlite_root.glob("*_repository.py")
            if path.name != "__init__.py"
        }
        if sqlite_root.exists()
        else set()
    )
    for name in sorted(port_files - sqlite_files):
        violations.append(f"missing SQLite mirror for ports/persistence/{name}")
    for name in sorted(sqlite_files - port_files):
        violations.append(f"missing persistence Port for sqlite/repositories/{name}")
    _assert_no_violations(violations)


def test_immediate_api_schema_and_langgraph_target_grammar() -> None:
    violations: list[str] = []
    schema_root = PACKAGE_ROOT / "api" / "schemas"
    if schema_root.exists():
        for path in sorted(schema_root.rglob("*.py")):
            if path.name == "__init__.py":
                continue
            relative = path.relative_to(schema_root)
            if len(relative.parts) != 2:
                violations.append(f"API schema must be resource-local: {_relative(path)}")
            if not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+\.py", path.name):
                violations.append(f"invalid API schema operation filename: {_relative(path)}")

    langgraph_root = PACKAGE_ROOT / "adapters" / "langgraph"
    if langgraph_root.exists():
        for routing_root in sorted(langgraph_root.rglob("routing")):
            if not routing_root.is_dir():
                continue
            for path in sorted(routing_root.glob("*.py")):
                if path.name == "__init__.py":
                    continue
                if not path.name.startswith("route_after_"):
                    violations.append(f"invalid LangGraph router filename: {_relative(path)}")
        for nodes_root in sorted(langgraph_root.rglob("nodes")):
            if not nodes_root.is_dir():
                continue
            for path in sorted(nodes_root.glob("*.py")):
                if path.name != "__init__.py" and not path.name.endswith("_node.py"):
                    violations.append(f"invalid LangGraph node filename: {_relative(path)}")
        for projections_root in sorted(langgraph_root.rglob("projections")):
            if not projections_root.is_dir():
                continue
            for path in sorted(projections_root.glob("*.py")):
                if path.name != "__init__.py" and not path.name.endswith("_projection.py"):
                    violations.append(f"invalid LangGraph projection filename: {_relative(path)}")
    _assert_no_violations(violations)


def test_immediate_canonical_dependency_direction_and_provider_boundary() -> None:
    violations: list[str] = []
    for path in _canonical_target_files():
        parts = _package_parts(path)
        imports = _imported_modules(path)
        for module in sorted(imports):
            module_parts = _module_parts(module)
            if module.startswith(tuple(PROVIDER_SDK_ROOTS)) and parts[:2] != (
                "adapters",
                "connectors",
            ):
                violations.append(f"Core direct Provider SDK import: {_relative(path)} -> {module}")
            if not module_parts:
                continue
            if parts[0] == "domain" and module_parts[0] != "domain":
                violations.append(f"Domain outward dependency: {_relative(path)} -> {module}")
            elif parts[0] == "application" and module_parts[0] == "adapters":
                violations.append(
                    f"Application concrete Adapter import: {_relative(path)} -> {module}"
                )
            elif parts[:2] == ("adapters", "langgraph"):
                if module_parts[:3] == ("adapters", "persistence", "sqlite"):
                    violations.append(
                        f"LangGraph concrete SQLite import: {_relative(path)} -> {module}"
                    )
                if module_parts[:1] == ("domain",) and "transitions" in module_parts:
                    violations.append(
                        f"LangGraph Domain transition import: {_relative(path)} -> {module}"
                    )
            elif parts[:2] == ("adapters", "persistence") and module_parts[0] == "application":
                violations.append(f"Persistence Application import: {_relative(path)} -> {module}")
            elif parts[:2] == ("adapters", "connectors") and module_parts[0] == "application":
                violations.append(f"Connector Application import: {_relative(path)} -> {module}")
            if module_parts and module_parts[0] in {"evaluation", "experiments"}:
                violations.append(f"Production imports Evaluation: {_relative(path)} -> {module}")
    _assert_no_violations(violations)


def test_immediate_concrete_barrels_do_not_hide_authority() -> None:
    violations: list[str] = []
    concrete_roots = (
        PACKAGE_ROOT / "application" / "use_cases",
        PACKAGE_ROOT / "application" / "agents",
        PACKAGE_ROOT / "adapters" / "langgraph",
        PACKAGE_ROOT / "adapters" / "persistence" / "sqlite" / "repositories",
        PACKAGE_ROOT / "adapters" / "connectors",
    )
    for root in concrete_roots:
        if not root.exists():
            continue
        for init_path in sorted(root.rglob("__init__.py")):
            if "contracts" in init_path.parts:
                continue
            tree = _parse(init_path)
            if any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in tree.body):
                violations.append(f"concrete barrel export hides authority: {_relative(init_path)}")
    _assert_no_violations(violations)


@pytest.mark.skipif(
    not FINAL_CUTOVER,
    reason="final structural cutover gate; set GWA_ARCHITECTURE_FINAL_CUTOVER=1",
)
def test_final_cutover_top_level_directory_ownership() -> None:
    allowed = {"domain", "application", "ports", "adapters", "api", "launcher", "__pycache__"}
    violations = [
        f"non-canonical top-level production owner: {_relative(path)}"
        for path in PACKAGE_ROOT.iterdir()
        if path.is_dir() and path.name not in allowed
    ]
    _assert_no_violations(violations)


@pytest.mark.skipif(
    not FINAL_CUTOVER,
    reason="final structural cutover gate; set GWA_ARCHITECTURE_FINAL_CUTOVER=1",
)
def test_final_cutover_has_no_forbidden_or_compat_authority() -> None:
    violations: list[str] = []
    for path in _production_python_files():
        if _is_forbidden_filename(path):
            violations.append(f"forbidden final production filename: {_relative(path)}")
        if any("_compat" in part for part in path.parts):
            violations.append(f"_compat must be zero at cutover: {_relative(path)}")
    _assert_no_violations(violations)


@pytest.mark.skipif(
    not FINAL_CUTOVER,
    reason="final structural cutover gate; set GWA_ARCHITECTURE_FINAL_CUTOVER=1",
)
def test_final_cutover_has_no_legacy_broad_authority() -> None:
    forbidden = {
        PACKAGE_ROOT / "domain" / "commands.py",
        PACKAGE_ROOT / "domain" / "transitions.py",
        PACKAGE_ROOT / "domain" / "guards.py",
        PACKAGE_ROOT / "application" / "ports",
        PACKAGE_ROOT / "application" / "workflows",
        PACKAGE_ROOT / "contracts",
    }
    violations = [
        f"legacy authority remains: {_relative(path)}"
        for path in forbidden
        if path.exists()
    ]
    for contracts_dir in PACKAGE_ROOT.rglob("contracts"):
        if not contracts_dir.is_dir():
            continue
        parts = contracts_dir.relative_to(PACKAGE_ROOT).parts
        owner_local = (
            len(parts) == 4
            and parts[:2] == ("application", "agents")
            and parts[2] in AGENT_CAPABILITIES
            and parts[3] == "contracts"
        )
        if not owner_local:
            violations.append(f"global/non-owner contracts package: {_relative(contracts_dir)}")
    _assert_no_violations(violations)


@pytest.mark.skipif(
    not FINAL_CUTOVER,
    reason="final structural cutover gate; set GWA_ARCHITECTURE_FINAL_CUTOVER=1",
)
def test_final_cutover_agent_capability_has_one_authority() -> None:
    violations: list[str] = []
    agent_root = PACKAGE_ROOT / "application" / "agents"
    for role, capabilities in AGENT_CAPABILITIES.items():
        for capability in sorted(capabilities):
            expected = agent_root / role / f"{capability}.py"
            candidates = sorted(agent_root.rglob(f"{capability}.py")) if agent_root.exists() else []
            if candidates != [expected]:
                rendered = ", ".join(_relative(path) for path in candidates) or "NONE"
                violations.append(
                    f"{role}.{capability} authority must be exactly "
                    f"{_relative(expected)}; found {rendered}"
                )
    _assert_no_violations(violations)


@pytest.mark.skipif(
    not FINAL_CUTOVER,
    reason="final structural cutover gate; set GWA_ARCHITECTURE_FINAL_CUTOVER=1",
)
def test_final_cutover_dependency_and_provider_boundaries_repo_wide() -> None:
    violations: list[str] = []
    for path in _production_python_files():
        parts = _package_parts(path)
        for module in sorted(_imported_modules(path)):
            module_parts = _module_parts(module)
            if module.startswith(tuple(PROVIDER_SDK_ROOTS)) and parts[:2] != (
                "adapters",
                "connectors",
            ):
                violations.append(f"Core direct Provider SDK import: {_relative(path)} -> {module}")
            if module_parts and module_parts[0] in {"evaluation", "experiments"}:
                violations.append(f"Production imports Evaluation: {_relative(path)} -> {module}")
            if parts[0] == "domain" and module_parts and module_parts[0] != "domain":
                violations.append(f"Domain outward dependency: {_relative(path)} -> {module}")
            if parts[0] == "application" and module_parts[:1] == ("adapters",):
                violations.append(
                    f"Application concrete Adapter import: {_relative(path)} -> {module}"
                )
    _assert_no_violations(violations)
