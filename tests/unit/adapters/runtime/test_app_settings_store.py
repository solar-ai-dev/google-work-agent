from __future__ import annotations

import json
from pathlib import Path

import pytest

from google_work_agent.adapters.system.json_settings import (
    FileSettingsStore,
    JsonSettingsAdapter,
)
from google_work_agent.ports.system.settings_port import SettingsPatchV1, SettingsViewV1


def _adapter(tmp_path: Path) -> JsonSettingsAdapter:
    return JsonSettingsAdapter(store=FileSettingsStore(tmp_path / "app-settings.json"))


def test_settings_update__replays_same__operation_and_reconciles(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    patch = SettingsPatchV1(schema_version=1, theme="DARK", retention_days=7)

    first = adapter.update_settings(patch, "settings-op-1")
    replay = adapter.update_settings(patch, "settings-op-1")

    assert replay == first
    assert replay.theme == "DARK"
    assert replay.retention_days == 7
    assert adapter.reconcile_settings("settings-op-1", patch).status == "COMPLETED"


def test_settings_operation__ref_conflict__fails_closed(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.update_settings(SettingsPatchV1(schema_version=1, theme="DARK"), "settings-op-1")

    with pytest.raises(ValueError, match="different settings patch"):
        adapter.update_settings(SettingsPatchV1(schema_version=1, theme="LIGHT"), "settings-op-1")


def test_settings_patch__omits_concrete__local_model_selection(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)

    updated = adapter.update_settings(
        SettingsPatchV1(
            schema_version=1,
            preferred_llm_mode="LOCAL_GPU",
        ),
        "settings-local-model-1",
    )

    assert updated.preferred_llm_mode == "LOCAL_GPU"
    assert "preferred_local_model_id" not in SettingsPatchV1.__dataclass_fields__


def test_settings_previous_field_set__when_loaded__adds_local_model_and_preserves_marker(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    adapter.update_settings(SettingsPatchV1(schema_version=1, theme="DARK"), "settings-op-1")
    path = tmp_path / "app-settings.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["settings"]["preferred_local_model_id"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    settings, marker = FileSettingsStore(path).load()

    assert settings.preferred_local_model_id is None
    assert marker is not None
    assert marker["operation_ref"] == "settings-op-1"


def test_settings_unknown__persisted_field__fails_closed(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.get_settings()
    path = tmp_path / "app-settings.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["unknown"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown fields"):
        adapter.get_settings()


def test_settings_exact__legacy_flat_envelope__migrates_atomically(tmp_path: Path) -> None:
    path = tmp_path / "app-settings.json"
    path.write_text(
        json.dumps(
            {
                "approval_ttl_minutes": 30,
                "approved_model_id": "legacy-model",
                "config_schema_version": 1,
                "default_calendar_id": "calendar-1",
                "default_tasklist_id": "tasks-1",
                "deployment_profile": "API_ONLY",
                "external_llm_consent": True,
                "log_level": "INFO",
                "ollama_endpoint": "http://127.0.0.1:11434",
                "requested_runtime_mode": "API_LLM",
                "run_retention_days": 14,
                "timezone": "Asia/Seoul",
                "work_hours": {
                    "days": [0, 1, 2, 3, 4],
                    "end": "18:00",
                    "start": "09:00",
                },
            }
        ),
        encoding="utf-8",
    )

    settings, marker = FileSettingsStore(path).load()

    assert marker is None
    assert settings.default_calendar_id == "calendar-1"
    assert settings.default_tasklist_id == "tasks-1"
    assert settings.preferred_llm_mode == "API_LLM"
    assert settings.external_llm_consent is True
    assert settings.retention_days == 14
    assert settings.working_day_start_local == "09:00"
    assert settings.working_day_end_local == "18:00"
    assert settings.include_weekends is False
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert set(persisted) == {"last_operation", "schema_version", "settings"}
    assert set(persisted["settings"]) == set(SettingsViewV1.__dataclass_fields__)
    assert "approved_model_id" not in persisted["settings"]
