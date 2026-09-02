from __future__ import annotations

import ast
from pathlib import Path

LAUNCHER_ROOT = Path("launcher")
SOURCE_ROOT = Path("src/google_work_agent")
LEGACY_LAUNCHER_PREFIX = "google_work_agent." + "launcher"

EXPECTED_OPERATIONS = {
    "entrypoint.py": {"main"},
    "acquire_single_instance.py": {"acquire_single_instance"},
    "verify_installation.py": {"verify_installation"},
    "release_build_config.py": {"SignedBuildConfigV1", "load_signed_build_config"},
    "prepare_data_directory.py": {"prepare_data_directory"},
    "allocate_dynamic_port.py": {"allocate_dynamic_port"},
    "bootstrap_secret.py": {"create_bootstrap_secret"},
    "create_service_instance_id.py": {"create_service_instance_id"},
    "start_service.py": {"start_service"},
    "readiness.py": {"wait_for_service_ready"},
    "serve_instance_control.py": {"serve_instance_control"},
    "request_existing_instance_ui.py": {"request_existing_instance_ui"},
    "open_product_ui.py": {"open_product_ui"},
    "shutdown_service.py": {"shutdown_service"},
}


def test_launcher_file__and_formal_operation__sets_are_exact() -> None:
    actual_files = {path.name for path in LAUNCHER_ROOT.glob("*.py") if path.name != "__init__.py"}
    assert actual_files == set(EXPECTED_OPERATIONS)

    for filename, required_symbols in EXPECTED_OPERATIONS.items():
        tree = ast.parse((LAUNCHER_ROOT / filename).read_text(encoding="utf-8"))
        actual_symbols = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        assert required_symbols <= actual_symbols, filename


def test_legacy_packaged__launcher_authority_and__callers_are_absent() -> None:
    assert list((SOURCE_ROOT / "launcher").glob("*.py")) == []
    assert not (SOURCE_ROOT / "adapters" / "runtime" / "launcher.py").exists()
    assert not (SOURCE_ROOT / "adapters" / "runtime" / "crash.py").exists()
    production_sources = [*SOURCE_ROOT.rglob("*.py"), *Path("scripts").glob("*.py")]
    offenders = [
        path
        for path in production_sources
        if LEGACY_LAUNCHER_PREFIX in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_launcher_has_no__core_business_or__second_composition_authority() -> None:
    forbidden_imports = (
        "google_work_agent.application",
        "google_work_agent.domain",
        "google_work_agent.adapters.connectors",
        "google_work_agent.adapters.langgraph",
        "google_work_agent.adapters.llm",
        "google_work_agent.adapters.persistence",
        "google_work_agent.api",
    )
    violations: list[str] = []
    for path in LAUNCHER_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = node.names[0].name
            if module.startswith(forbidden_imports):
                violations.append(f"{path}:{module}")
    assert violations == []


def test_runtime_artifact_writers__do_not_contain__bootstrap_or_provider_secrets() -> None:
    artifact_owners = (
        LAUNCHER_ROOT / "acquire_single_instance.py",
        LAUNCHER_ROOT / "create_service_instance_id.py",
        LAUNCHER_ROOT / "shutdown_service.py",
    )
    forbidden = ("bootstrap_secret", "client_secret", "access_token", "refresh_token", "api_key")
    violations = [
        f"{path}:{term}"
        for path in artifact_owners
        for term in forbidden
        if term in path.read_text(encoding="utf-8").lower()
    ]
    assert violations == []


def test_signed_locked__fields_have_no__ambient_launcher_override() -> None:
    signed_fields = (
        "APP_VERSION",
        "BUILD_CHANNEL",
        "DEPLOYMENT_PROFILE",
        "OAUTH_ENV",
        "OAUTH_CLIENT_ID",
        "API_CONTRACT_VERSION",
        "MCP_SCHEMA_VERSION",
        "POLICY_VERSION",
        "DATABASE_MIGRATION_VERSION",
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in LAUNCHER_ROOT.glob("*.py"))
    for field in signed_fields:
        assert f'os.environ.get("{field}")' not in source
        assert f'os.getenv("{field}")' not in source
    assert "GOOGLE_OAUTH_CLIENT_SECRET" not in source
