from __future__ import annotations

import json

import pytest

from google_work_agent.adapters.connectors.runtime.load_installed_connector_manifest import (
    load_installed_connector_manifest,
)


def test_installed_manifest_has_one_canonical_google_workspace_binding() -> None:
    entry = load_installed_connector_manifest().get_required("google_workspace")

    assert entry.provider_namespace == "google"
    assert entry.connector_package == "workspace"
    assert entry.tool_projection_path.endswith("tool-descriptor-projection-v1.json")


def test_installed_manifest_rejects_duplicate_and_unsafe_paths(tmp_path) -> None:
    source = load_installed_connector_manifest.__globals__["_IMPLEMENTATION_MANIFEST"]
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["connectors"][0]["executable_path"] = "../escape.exe"
    path = tmp_path / "installed.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="safe and relative"):
        load_installed_connector_manifest(path)
    with pytest.raises(ValueError, match="release hash mismatch"):
        load_installed_connector_manifest(source, expected_sha256="0" * 64)
