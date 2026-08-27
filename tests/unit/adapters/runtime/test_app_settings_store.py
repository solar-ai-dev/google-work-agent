from __future__ import annotations

import json
from pathlib import Path

import pytest

from google_work_agent.adapters.system.json_settings import (
    FileSettingsStore,
    JsonSettingsAdapter,
)
from google_work_agent.ports.system.settings_port import SettingsPatchV1


def _adapter(tmp_path: Path) -> JsonSettingsAdapter:
    return JsonSettingsAdapter(store=FileSettingsStore(tmp_path / "app-settings.json"))


def test_settings_update_replays_same_operation_and_reconciles(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    patch = SettingsPatchV1(schema_version=1, theme="DARK", retention_days=7)

    first = adapter.update_settings(patch, "settings-op-1")
    replay = adapter.update_settings(patch, "settings-op-1")

    assert replay == first
    assert replay.theme == "DARK"
    assert replay.retention_days == 7
    assert adapter.reconcile_settings("settings-op-1", patch).status == "COMPLETED"


def test_settings_operation_ref_conflict_fails_closed(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.update_settings(SettingsPatchV1(schema_version=1, theme="DARK"), "settings-op-1")

    with pytest.raises(ValueError, match="different settings patch"):
        adapter.update_settings(
            SettingsPatchV1(schema_version=1, theme="LIGHT"), "settings-op-1"
        )


def test_settings_unknown_persisted_field_fails_closed(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.get_settings()
    path = tmp_path / "app-settings.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["unknown"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown fields"):
        adapter.get_settings()
