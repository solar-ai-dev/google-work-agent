"""Unit tests for FileSettingsStore/JsonSettingsAdapter approved_model_id round-trip.

Regression coverage: `FileSettingsStore.load()` used to call
`validate_settings(...)` without an `approved_model_ids` allowlist, so it
always defaulted to None and *any* previously-saved non-null
`approved_model_id` made every subsequent settings read raise
`ValueError("approved_model_id is not allowed")` -- even one that
`JsonSettingsAdapter.patch()` had itself just validated and written.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from google_work_agent.adapters.runtime.build_manifest import BuildProfile
from google_work_agent.adapters.system.json_settings import (
    FileSettingsStore,
    JsonSettingsAdapter,
    SettingsPatch,
)


def _service(tmp_path: Path, *, approved_model_ids: frozenset[str]) -> JsonSettingsAdapter:
    return JsonSettingsAdapter(
        store=FileSettingsStore(tmp_path / "app-settings.json"),
        deployment_profile=BuildProfile.LOCAL_CAPABLE,
        approved_model_ids=approved_model_ids,
        has_active_runs=lambda: False,
    )


def test_patched_approved_model_id_survives_a_subsequent_get(tmp_path: Path) -> None:
    service = _service(tmp_path, approved_model_ids=frozenset({"qwen2.5:3b"}))

    patched = service.patch(SettingsPatch(command_id="cmd-1", approved_model_id="qwen2.5:3b"))
    assert patched.approved_model_id == "qwen2.5:3b"

    reloaded = service.get()
    assert reloaded.approved_model_id == "qwen2.5:3b"


def test_get_still_rejects_an_approved_model_id_outside_the_allowlist(tmp_path: Path) -> None:
    writer = _service(tmp_path, approved_model_ids=frozenset({"qwen2.5:3b"}))
    writer.patch(SettingsPatch(command_id="cmd-1", approved_model_id="qwen2.5:3b"))

    reader = _service(tmp_path, approved_model_ids=frozenset({"a-different-model"}))
    with pytest.raises(ValueError, match="approved_model_id is not allowed"):
        reader.get()


def test_file_settings_store_load_defaults_to_no_allowlist(tmp_path: Path) -> None:
    store = FileSettingsStore(tmp_path / "app-settings.json")
    settings = store.load(deployment_profile=BuildProfile.LOCAL_CAPABLE)
    assert settings.approved_model_id is None
    assert settings.setup_completed is False


def test_setup_completion_round_trips_through_settings_store(tmp_path: Path) -> None:
    service = _service(tmp_path, approved_model_ids=frozenset())

    service.patch(SettingsPatch(command_id="cmd-setup", setup_completed=True))

    assert service.get().setup_completed is True
