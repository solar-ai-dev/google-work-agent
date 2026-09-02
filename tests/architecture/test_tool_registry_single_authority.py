from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from tests.support.production_runtime import build_test_production_container

from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import (
    MCPConnectorDescriptor,
)
from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    SessionMemorySecretStore,
)
from google_work_agent.api import composition
from google_work_agent.api.composition import _VerifiedReleaseFile
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.tool_registry.signed_tool_registry import (
    SignedToolRegistry,
)

ROOT = Path("src/google_work_agent")
PRODUCTION_ROOTS = (ROOT, Path("launcher"), Path("release"), Path("scripts"))
INNER_ROOTS = (
    ROOT / "application/use_cases",
    ROOT / "domain",
    ROOT / "adapters/langgraph",
    ROOT / "api/routes",
)


def _python_files(roots: tuple[Path, ...]) -> list[Path]:
    return sorted(path for root in roots if root.exists() for path in root.rglob("*.py"))


def _calls(path: Path, function_name: str) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == function_name
    ]


def test_production_inner_layers_have__zero_default__tool_registry_loads() -> None:
    offenders = [
        path
        for path in _python_files(INNER_ROOTS)
        if any(
            not call.args and not call.keywords
            for call in _calls(path, "load_signed_tool_registry")
        )
    ]

    assert offenders == []


def test_signed_runtime_has__one_explicit_registry_load__and_one_constructor_authority() -> None:
    composition_path = ROOT / "api/composition.py"
    signed_runtime_loads = _calls(composition_path, "load_signed_tool_registry")
    constructor_owners = [
        path
        for path in _python_files(PRODUCTION_ROOTS)
        if _calls(path, "SignedToolRegistry")
    ]

    assert len(signed_runtime_loads) == 1
    assert signed_runtime_loads[0].args
    assert constructor_owners == [
        ROOT / "application/tool_registry/load_signed_tool_registry.py"
    ]


def test_development_composition_loads__one_registry_instance__for_all_consumers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    actual_loader = composition.load_development_tool_registry
    loaded: list[SignedToolRegistry] = []

    def load_once() -> SignedToolRegistry:
        registry = actual_loader()
        loaded.append(registry)
        return registry

    monkeypatch.setattr(composition, "load_development_tool_registry", load_once)
    container = build_test_production_container(
        runtime_root=tmp_path / "runtime",
        mcp_module_name="tests.fakes.mcp_server",
        keyring_store=SessionMemorySecretStore(),
    )
    try:
        assert len(loaded) == 1
        registry = loaded[0]
        workflow: Any = container.workflow_runtime
        approve_action = container.approve_action_handler
        modify_action = container.modify_action_handler
        assert approve_action is not None
        assert modify_action is not None
        consumers = (
            approve_action._registry,
            modify_action._registry,
            workflow._claim_execution._registry,
            workflow._canonical_domain_validation._tool_registry,
            workflow._write_execution_phase._connector_execution._dispatch_connector_write._tool_registry,
            workflow._store_write_success._tool_registry,
            workflow._verify_effect._tool_registry,
            workflow._lookup_unknown_result._tool_registry,
            workflow._recover_existing_result._tool_registry,
        )

        assert all(consumer is registry for consumer in consumers)
        assert {consumer.entries_hash for consumer in consumers} == {registry.entries_hash}
    finally:
        for close in reversed(container.shutdown_callbacks):
            close()


def test_signed_connector_composition_uses__verified_installed_registry_when__embedded_drifts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_root = tmp_path / "install"
    registry_path = install_root / "manifests/signed-tool-registry-v1.json"
    installed_path = install_root / "manifests/installed-connectors-v1.json"
    executable_path = install_root / "mcp/google_workspace/GoogleWorkspaceMcpServer.exe"
    projection_path = (
        install_root
        / "manifests/connectors/google_workspace/tool-descriptor-projection-v1.json"
    )
    embedded_path = load_signed_tool_registry.__globals__["_IMPLEMENTATION_MANIFEST"]
    embedded_payload = json.loads(embedded_path.read_text(encoding="utf-8"))
    installed_payload = {
        "schema_version": 1,
        "connectors": [
            {
                "schema_version": 1,
                "connector_id": "google_workspace",
                "provider_namespace": "google",
                "connector_package": "workspace",
                "executable_path": "mcp/google_workspace/GoogleWorkspaceMcpServer.exe",
                "tool_projection_path": (
                    "manifests/connectors/google_workspace/"
                    "tool-descriptor-projection-v1.json"
                ),
                "mcp_schema_version": "2026-08-07.p0",
            }
        ],
    }
    installed_registry_payload = json.loads(json.dumps(embedded_payload))
    installed_registry_payload["contract_version"] = "2026-08-06.drift-proof"
    installed_registry_payload["entries"][0]["input_schema_ref"] = "drift-proof-v2"
    installed_registry_payload["entries_hash"] = hashlib.sha256(
        json.dumps(
            installed_registry_payload["entries"], separators=(",", ":"), sort_keys=True
        ).encode()
    ).hexdigest()
    for path in (registry_path, installed_path, executable_path, projection_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(installed_registry_payload), encoding="utf-8")
    installed_path.write_text(json.dumps(installed_payload), encoding="utf-8")
    executable_path.write_bytes(b"signed executable")
    projection_path.write_text("{}", encoding="utf-8")

    captured_descriptors: list[MCPConnectorDescriptor] = []

    class _ConnectorWithoutProcess:
        def __init__(
            self, *, descriptor: MCPConnectorDescriptor, **_kwargs: object
        ) -> None:
            captured_descriptors.append(descriptor)

        def start(self) -> None:
            return None

    monkeypatch.setattr(composition, "GoogleWorkspaceConnector", _ConnectorWithoutProcess)
    paths = (installed_path, registry_path, executable_path, projection_path)
    release_files = tuple(_verified_file(install_root, path) for path in paths)
    bundle = composition._build_connectors(
        mcp_manifest_path=tmp_path / "ignored-development-manifest.json",
        mcp_manifest_version="2026-08-07.p0",
        service_instance_id="registry-drift-test",
        attachment_staging_dir=tmp_path / "attachments",
        python_executable=Path("ignored-python.exe"),
        working_directory=install_root.resolve(),
        environment="DEVELOPMENT",
        oauth_client_id="test-client",
        development_tool_registry=None,
        configuration_source="SIGNED_RELEASE_MANIFEST",
        verified_release_files=release_files,
        code_signature_verified_paths=frozenset(),
    )

    assert bundle.tool_registry.contract_version == "2026-08-06.drift-proof"
    assert bundle.tool_registry.entries_hash == installed_registry_payload["entries_hash"]
    assert bundle.tool_registry.entries_hash != embedded_payload["entries_hash"]
    assert len(captured_descriptors) == 1
    descriptor = captured_descriptors[0]
    assert descriptor.artifact_config.expected_registry_manifest_hash == (
        bundle.tool_registry.entries_hash
    )
    assert {entry.registry_entry_hash for entry in descriptor.expected_tool_descriptors} == {
        entry.registry_entry_hash for entry in bundle.tool_registry.entries
    }


def _verified_file(install_root: Path, path: Path) -> _VerifiedReleaseFile:
    content = path.read_bytes()
    return _VerifiedReleaseFile(
        file_path=path.relative_to(install_root).as_posix(),
        file_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
