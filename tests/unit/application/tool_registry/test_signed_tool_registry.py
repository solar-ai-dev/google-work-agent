from __future__ import annotations

import json
from pathlib import Path

import pytest

from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)


def test_signed_registry_loads_exact_google_workspace_tool_set() -> None:
    registry = load_signed_tool_registry()

    assert len(registry.entries) == 21
    assert {entry.connector_id for entry in registry.entries} == {"google_workspace"}
    assert registry.entries_hash == (
        "3092c76bfea70c819a244f4f47f5a41babd8726fbc902031087254d754fbd67d"
    )


def test_signed_registry_binds_effect_and_entry_hash() -> None:
    registry = load_signed_tool_registry()

    binding = registry.bind_required("google_workspace", "gmail_send", "SEND")

    assert binding.tool_id == "gmail_send"
    assert binding.effect == "SEND"
    assert len(binding.registry_entry_hash) == 64
    with pytest.raises(ValueError, match="effect mismatch"):
        registry.bind_required("google_workspace", "gmail_send", "READ")


def test_signed_registry_loader_rejects_manifest_drift(tmp_path: Path) -> None:
    source = load_signed_tool_registry.__globals__["_IMPLEMENTATION_MANIFEST"]
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="fields mismatch"):
        load_signed_tool_registry(path)
    with pytest.raises(ValueError, match="release hash mismatch"):
        load_signed_tool_registry(source, expected_sha256="0" * 64)

    path.write_text(
        '{"schema_version":1,"schema_version":1,"contract_version":"1",'
        '"entries":[],"entries_hash":"x"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate signed tool registry"):
        load_signed_tool_registry(path)
