from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "google_work_agent"
FINAL = os.getenv("GWA_ARCHITECTURE_FINAL_CUTOVER") == "1"

ROLES = {
    "request_understanding": {
        "identify_goal",
        "detect_ambiguity",
        "finalize_intent",
        "validate_intent",
    },
    "tool_routing": {
        "determine_io_resources",
        "resolve_policy_preconditions",
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
        "resolve_availability",
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
        "resolve_default_container",
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
ROLE_FILES = {"state.py", "graph.py", "model.py", "composition.py"}
BAD_NAMES = {
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
BAD_GENERATIONS = tuple(
    re.compile(p)
    for p in (
        r"canonical_.*\.py",
        r"production_.*\.py",
        r"legacy_.*\.py",
        r"new_.*\.py",
        r"old_.*\.py",
        r"final_.*\.py",
        r".*_v\d+\.py",
        r".*_r\d+\.py",
    )
)
PROVIDER_PREFIXES = (
    "googleapiclient",
    "google_auth_oauthlib",
    "google.auth",
    "google.oauth2",
    "google.cloud",
)


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def parts(path: Path) -> tuple[str, ...]:
    return path.relative_to(SRC).parts


def pyfiles() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def canonical(path: Path) -> bool:
    p = parts(path)
    if p[:1] == ("domain",) and len(p) >= 3 and p[1] in DOMAIN_OWNERS:
        return True
    if p[:2] == ("application", "use_cases") and len(p) >= 4:
        return True
    if p[:2] == ("application", "agents") and len(p) >= 4 and p[2] in ROLES:
        return True
    if p[:2] == ("ports", "persistence") and len(p) == 3:
        return True
    if p[:4] == ("adapters", "persistence", "sqlite", "repositories"):
        return True
    if p[:2] == ("adapters", "connectors") and len(p) >= 6:
        return True
    if p[:3] == ("adapters", "langgraph", "main") and len(p) >= 4:
        return True
    if p[:3] == ("adapters", "langgraph", "subgraphs") and len(p) >= 5 and p[3] in ROLES:
        return True
    if p[:2] == ("api", "schemas") and len(p) >= 4:
        return True
    return p[:2] in {("api", "routes"), ("api", "dependencies")} and len(p) == 3


def bad_name(path: Path) -> bool:
    if path.name in ROLE_FILES:
        return False
    return path.name in BAD_NAMES or any(rx.fullmatch(path.name) for rx in BAD_GENERATIONS)


def tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def functions(path: Path) -> set[str]:
    return {
        n.name for n in tree(path).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def classes(path: Path) -> set[str]:
    return {n.name for n in tree(path).body if isinstance(n, ast.ClassDef)}


def imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def internal(module: str) -> tuple[str, ...]:
    prefix = "google_work_agent."
    return tuple(module[len(prefix) :].split(".")) if module.startswith(prefix) else ()


def pascal(stem: str) -> str:
    acronyms = {"llm": "LLM", "oauth": "OAuth"}
    return "".join(acronyms.get(part, part.capitalize()) for part in stem.split("_"))


def owned_symbols(path: Path) -> set[str]:
    result = classes(path)
    for node in tree(path).body:
        if isinstance(node, ast.TypeAlias):
            if isinstance(node.name, ast.Name):
                result.add(node.name.id)
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            result.update(target.id for target in targets if isinstance(target, ast.Name))
    return result


def exported_symbols(path: Path) -> set[str]:
    result = owned_symbols(path)
    for node in tree(path).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            result.update(alias.asname or alias.name.rsplit(".", 1)[-1] for alias in node.names)
    return result


def application_ledger_contracts() -> dict[str, set[str]]:
    contracts: dict[str, set[str]] = {}
    ledger = ROOT / "implementation-inventory" / "ledger.md"
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| CAP-APP-"):
            continue
        escaped = line.replace(r"\|", "<PIPE>")
        fields = [field.strip().replace("<PIPE>", "|") for field in escaped.split("|")[1:-1]]
        directory, filename, symbol_field = fields[8:11]
        # Semicolon-delimited input/output descriptions name transport contracts,
        # not symbols owned by this Application module.
        owned_field = symbol_field.split(";", 1)[0]
        symbols = {
            symbol.strip()
            for symbol in owned_field.split("/")
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", symbol.strip())
        }
        contracts[f"{directory}{filename}"] = symbols
    return contracts


def clean(errors: list[str]) -> None:
    assert not errors, "\n" + "\n".join(f"- {e}" for e in errors)


def test_immediate_canonical_filename_grammar() -> None:
    clean(
        [
            f"forbidden canonical filename: {rel(p)}"
            for p in pyfiles()
            if canonical(p) and bad_name(p)
        ]
    )


def test_immediate_module_package_authority_is_unique() -> None:
    clean(
        [
            f"module/package authority collision: {rel(path)}"
            for path in pyfiles()
            if path.name != "__init__.py" and path.with_suffix("").is_dir()
        ]
    )


def test_immediate_domain_operation_per_file() -> None:
    errors: list[str] = []
    for owner in DOMAIN_OWNERS:
        base = SRC / "domain" / owner
        if not base.exists():
            continue
        for child in base.iterdir():
            if child.is_dir() and child.name not in {"transitions", "guards", "__pycache__"}:
                errors.append(f"unexpected domain directory: {rel(child)}")
            elif (
                child.is_file()
                and child.suffix == ".py"
                and child.name not in {"__init__.py", "model.py"}
            ):
                errors.append(f"unexpected domain module: {rel(child)}")
        for folder, prefix in (("transitions", "transition_"), ("guards", "guard_")):
            opdir = base / folder
            if not opdir.exists():
                continue
            for path in opdir.glob("*.py"):
                if path.name != "__init__.py" and f"{prefix}{path.stem}" not in functions(path):
                    errors.append(f"{rel(path)} must define {prefix}{path.stem}()")
    clean(errors)


def test_immediate_application_use_case_grammar() -> None:
    errors: list[str] = []
    for relative_path, expected_symbols in application_ledger_contracts().items():
        path = SRC / relative_path
        if not path.is_file():
            errors.append(f"missing Application capability module: {rel(path)}")
            continue
        missing = expected_symbols - exported_symbols(path)
        if missing:
            errors.append(f"{rel(path)} missing exact symbols: {sorted(missing)}")
    clean(errors)


def test_immediate_agent_atomic_grammar() -> None:
    errors: list[str] = []
    base = SRC / "application" / "agents"
    if not base.exists():
        return
    errors.extend(
        f"unknown agent owner: {p.name}"
        for p in base.iterdir()
        if p.is_dir() and p.name not in ROLES and p.name != "__pycache__"
    )
    for role, allowed in ROLES.items():
        owner = base / role
        if not owner.exists():
            continue
        for path in owner.glob("*.py"):
            if path.name == "__init__.py":
                continue
            if path.stem not in allowed:
                errors.append(f"unknown/broad agent capability: {rel(path)}")
            elif path.stem not in functions(path):
                errors.append(f"{rel(path)} must define {path.stem}()")
    clean(errors)


def test_immediate_persistence_port_sqlite_mirror() -> None:
    ports = SRC / "ports" / "persistence"
    sqlite = SRC / "adapters" / "persistence" / "sqlite" / "repositories"
    left = {p.name for p in ports.glob("*_repository.py")} if ports.exists() else set()
    right = {p.name for p in sqlite.glob("*_repository.py")} if sqlite.exists() else set()
    clean(
        [
            *(f"missing SQLite mirror: {n}" for n in sorted(left - right)),
            *(f"missing persistence Port: {n}" for n in sorted(right - left)),
        ]
    )


def test_immediate_api_and_langgraph_target_grammar() -> None:
    errors: list[str] = []
    schemas = SRC / "api" / "schemas"
    canonical_shared_schemas = {("runs", "recovery.py")}
    if schemas.exists():
        for resource in (p for p in schemas.iterdir() if p.is_dir()):
            for path in resource.glob("*.py"):
                if (
                    path.name != "__init__.py"
                    and "_" not in path.stem
                    and (resource.name, path.name) not in canonical_shared_schemas
                ):
                    errors.append(f"API schema must be <verb>_<object>.py: {rel(path)}")
    lg = SRC / "adapters" / "langgraph"
    targets = [lg / "main", *(lg / "subgraphs" / role for role in ROLES)]
    for base in targets:
        if not base.exists():
            continue
        checks = (
            ("routing", lambda n: n.startswith("route_after_")),
            ("nodes", lambda n: n.endswith("_node")),
            ("projections", lambda n: n.endswith("_projection")),
        )
        for folder, valid in checks:
            opdir = base / folder
            if not opdir.exists():
                continue
            for path in opdir.glob("*.py"):
                if path.name != "__init__.py" and not valid(path.stem):
                    errors.append(f"invalid LangGraph {folder} file: {rel(path)}")
    clean(errors)


def test_immediate_dependency_and_provider_boundary() -> None:
    errors: list[str] = []
    for path in (p for p in pyfiles() if canonical(p)):
        p = parts(path)
        for module in imports(path):
            m = internal(module)
            if module.startswith(PROVIDER_PREFIXES) and p[:2] != ("adapters", "connectors"):
                errors.append(f"Core direct Provider SDK: {rel(path)} -> {module}")
            if not m:
                continue
            if p[0] == "domain" and m[0] != "domain":
                errors.append(f"Domain outward import: {rel(path)} -> {module}")
            if p[0] == "application" and m[0] == "adapters":
                errors.append(f"Application concrete Adapter import: {rel(path)} -> {module}")
            if p[:2] == ("adapters", "langgraph") and m[:3] in {
                ("adapters", "persistence", "sqlite"),
                ("adapters", "system", "sqlite_checkpoint"),
            }:
                errors.append(f"LangGraph concrete SQLite import: {rel(path)} -> {module}")
            if p[:2] == ("adapters", "langgraph") and m[:1] == ("domain",) and "transitions" in m:
                errors.append(f"LangGraph Domain transition import: {rel(path)} -> {module}")
            if p[:2] == ("adapters", "persistence") and m[:1] == ("application",):
                errors.append(f"Persistence Application import: {rel(path)} -> {module}")
            if p[:2] == ("adapters", "connectors") and m[:1] == ("application",):
                errors.append(f"Connector Application import: {rel(path)} -> {module}")
            if m[:1] in {("evaluation",), ("experiments",)}:
                errors.append(f"Production imports Evaluation: {rel(path)} -> {module}")
    clean(errors)


def test_immediate_concrete_barrel_authority() -> None:
    errors: list[str] = []
    for path in (p for p in pyfiles() if canonical(p) and p.name == "__init__.py"):
        if "contracts" in parts(path):
            continue
        if any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in tree(path).body):
            errors.append(f"concrete barrel hides authority: {rel(path)}")
    clean(errors)


def test_immediate_public_alias_reexport_and_duplicate_definition_zero() -> None:
    errors: list[str] = []
    definitions: dict[tuple[type[ast.AST], str], list[Path]] = {}
    for path in pyfiles():
        module = tree(path)
        material_nodes = [
            node
            for node in module.body
            if not isinstance(node, (ast.Import, ast.ImportFrom))
            and not (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            )
            and not (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "__all__"
                    for target in node.targets
                )
            )
        ]
        if (
            any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in module.body)
            and not material_nodes
        ):
            errors.append(f"reexport-only production module: {rel(path)}")
        for node in module.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and not node.targets[0].id.startswith("_")
                and isinstance(node.value, (ast.Name, ast.Attribute))
            ):
                errors.append(f"public alias: {rel(path)}:{node.targets[0].id}")
            if isinstance(
                node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ) and not node.name.startswith("_"):
                definitions.setdefault((type(node), node.name), []).append(path)
    for (_, name), owners in definitions.items():
        unique_owners = sorted(set(owners))
        if len(unique_owners) > 1:
            errors.append(
                f"duplicate public definition {name}: {', '.join(map(rel, unique_owners))}"
            )
    clean(errors)


def test_test_modules_import_only_support_not_peer_tests() -> None:
    tests_root = ROOT / "tests"
    errors: list[str] = []
    for path in tests_root.rglob("*.py"):
        owner_package = path.relative_to(ROOT).with_suffix("").parts[:-1]
        imported_modules: set[str] = set()
        for node in ast.walk(tree(path)):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level:
                anchor = owner_package[: len(owner_package) - node.level + 1]
                imported_modules.add(".".join((*anchor, *((node.module or "").split(".")))))
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
        for module in imported_modules:
            if not module.startswith("tests.") or module.startswith("tests.support"):
                continue
            module_path = ROOT.joinpath(*module.split(".")).with_suffix(".py")
            package_path = ROOT.joinpath(*module.split("."), "__init__.py")
            if module_path.is_file() or package_path.is_file():
                errors.append(f"test-to-test import: {rel(path)} -> {module}")
    clean(errors)


@pytest.mark.skipif(not FINAL, reason="final cutover only: GWA_ARCHITECTURE_FINAL_CUTOVER=1")
def test_final_top_level_ownership() -> None:
    allowed = {"domain", "application", "ports", "adapters", "api", "launcher", "__pycache__"}
    clean(
        [
            f"non-canonical top-level owner: {rel(p)}"
            for p in SRC.iterdir()
            if p.is_dir() and p.name not in allowed
        ]
    )


@pytest.mark.skipif(not FINAL, reason="final cutover only: GWA_ARCHITECTURE_FINAL_CUTOVER=1")
def test_final_forbidden_names_and_compat_zero() -> None:
    errors: list[str] = []
    for path in pyfiles():
        if bad_name(path) and parts(path) != ("ports", "system", "contracts", "runtime.py"):
            errors.append(f"forbidden final filename: {rel(path)}")
        if "_compat" in path.parts:
            errors.append(f"_compat remains: {rel(path)}")
    clean(errors)


@pytest.mark.skipif(not FINAL, reason="final cutover only: GWA_ARCHITECTURE_FINAL_CUTOVER=1")
def test_final_legacy_authorities_retired() -> None:
    forbidden = [
        SRC / "domain" / "commands.py",
        SRC / "domain" / "transitions.py",
        SRC / "domain" / "guards.py",
        SRC / "application" / "ports",
        SRC / "application" / "workflows",
        SRC / "contracts",
    ]
    errors = [f"legacy authority remains: {rel(p)}" for p in forbidden if p.exists()]
    allowed_contract_packages = {
        ("application", "prompt_runtime", "contracts"),
        ("application", "tool_registry", "contracts"),
        ("ports", "connector", "contracts"),
        ("ports", "system", "contracts"),
    }
    for path in SRC.rglob("contracts"):
        p = path.relative_to(SRC).parts
        if path.is_dir() and not (
            (len(p) == 4 and p[:2] == ("application", "agents") and p[2] in ROLES)
            or p in allowed_contract_packages
        ):
            errors.append(f"non-owner contract package: {rel(path)}")
    clean(errors)


@pytest.mark.skipif(not FINAL, reason="final cutover only: GWA_ARCHITECTURE_FINAL_CUTOVER=1")
def test_final_agent_one_capability_one_authority() -> None:
    errors: list[str] = []
    base = SRC / "application" / "agents"
    for role, capabilities in ROLES.items():
        for capability in capabilities:
            expected = base / role / f"{capability}.py"
            found = sorted(base.rglob(f"{capability}.py")) if base.exists() else []
            if found != [expected]:
                found_text = ", ".join(map(rel, found)) or "NONE"
                errors.append(
                    f"{role}.{capability}: expected only {rel(expected)}; found {found_text}"
                )
    clean(errors)


@pytest.mark.skipif(not FINAL, reason="final cutover only: GWA_ARCHITECTURE_FINAL_CUTOVER=1")
def test_final_repo_wide_dependency_and_provider_boundary() -> None:
    errors: list[str] = []
    for path in pyfiles():
        p = parts(path)
        for module in imports(path):
            m = internal(module)
            if module.startswith(PROVIDER_PREFIXES) and p[:2] != ("adapters", "connectors"):
                errors.append(f"Core direct Provider SDK: {rel(path)} -> {module}")
            if m[:1] in {("evaluation",), ("experiments",)}:
                errors.append(f"Production imports Evaluation: {rel(path)} -> {module}")
            if p[0] == "domain" and m and m[0] != "domain":
                errors.append(f"Domain outward import: {rel(path)} -> {module}")
            if p[0] == "application" and m[:1] == ("adapters",):
                errors.append(f"Application concrete Adapter import: {rel(path)} -> {module}")
    clean(errors)
