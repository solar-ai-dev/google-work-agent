"""C4 architecture gates for Connector/MCP provider containment."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "google_work_agent"

_PROVIDER_MODULE_PREFIXES = (
    "googleapiclient",
    "google.auth",
    "google.oauth2",
    "google_auth_oauthlib",
    "google.api_core",
    "google.cloud",
)
_CORE_ROOTS = (
    SRC / "api",
    SRC / "application",
    SRC / "domain",
    SRC / "ports",
    SRC / "launcher",
    SRC / "adapters" / "langgraph",
)


def _python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return tuple(names)


def _is_provider_module(module_name: str) -> bool:
    return any(
        module_name == prefix or module_name.startswith(f"{prefix}.")
        for prefix in _PROVIDER_MODULE_PREFIXES
    )


def test_core_has_zero_direct_google_provider_sdk_imports() -> None:
    violations: list[str] = []
    for root in _CORE_ROOTS:
        for path in _python_files(root):
            for module_name in _imports(path):
                if _is_provider_module(module_name):
                    violations.append(f"{path.relative_to(ROOT)} -> {module_name}")

    assert violations == []


def test_core_has_zero_direct_google_provider_http_endpoints() -> None:
    violations: list[str] = []
    for root in _CORE_ROOTS:
        for path in _python_files(root):
            source = path.read_text(encoding="utf-8")
            if "googleapis.com" in source:
                violations.append(str(path.relative_to(ROOT)))

    assert violations == []


def test_google_connector_operations_do_not_import_provider_sdk() -> None:
    operation_root = SRC / "adapters" / "connectors" / "google"
    violations: list[str] = []
    for path in _python_files(operation_root):
        for module_name in _imports(path):
            if _is_provider_module(module_name):
                violations.append(f"{path.relative_to(ROOT)} -> {module_name}")

    assert violations == []


def test_connector_runtime_uses_canonical_subject_specific_module() -> None:
    connector_root = SRC / "adapters" / "connectors"
    assert not (connector_root / "runtime.py").exists()
    assert not (connector_root / "connector_mcp_runtime.py").exists()
    assert (connector_root / "runtime" / "connector_runtime_registry.py").is_file()
    assert (connector_root / "runtime" / "stdio_mcp_client.py").is_file()


def test_connector_adapter_package_does_not_reexport_owner_implementations() -> None:
    package_init = SRC / "adapters" / "connectors" / "__init__.py"
    tree = ast.parse(package_init.read_text(encoding="utf-8"), filename=str(package_init))
    violations: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("google_work_agent.adapters.connectors.")
        ):
            violations.append(node.module)

    assert violations == []


def test_production_callers_do_not_import_connector_adapter_barrel() -> None:
    package_name = "google_work_agent.adapters.connectors"
    package_init = SRC / "adapters" / "connectors" / "__init__.py"
    violations: list[str] = []
    for path in _python_files(SRC):
        if path == package_init:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == package_name
                or isinstance(node, ast.Import)
                and any(alias.name == package_name for alias in node.names)
            ):
                violations.append(str(path.relative_to(ROOT)))

    assert violations == []


def test_connector_port_boundary_does_not_depend_on_adapters() -> None:
    port_root = SRC / "ports" / "connectors"
    violations: list[str] = []
    for path in _python_files(port_root):
        for module_name in _imports(path):
            if module_name.startswith("google_work_agent.adapters"):
                violations.append(f"{path.relative_to(ROOT)} -> {module_name}")

    assert violations == []
