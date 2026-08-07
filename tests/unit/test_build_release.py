from __future__ import annotations

import json
from pathlib import Path

from scripts.build_release import build_release_from

from google_work_agent.adapters.runtime import BuildProfile


def test_build_release_profiles_emit_distinct_runtime_metadata(tmp_path: Path) -> None:
    frontend_dist = tmp_path / "frontend-dist"
    (frontend_dist / "assets").mkdir(parents=True)
    (frontend_dist / "index.html").write_text("<!doctype html><html></html>", encoding="utf-8")
    (frontend_dist / "assets" / "app.js").write_text("console.log('ui');", encoding="utf-8")

    api_manifest = build_release_from(
        profile=BuildProfile.API_ONLY,
        output_dir=tmp_path / "api-only",
        frontend_dist=frontend_dist,
    )
    local_manifest = build_release_from(
        profile=BuildProfile.LOCAL_CAPABLE,
        output_dir=tmp_path / "local-capable",
        frontend_dist=frontend_dist,
    )

    api_profile = json.loads(
        (tmp_path / "api-only" / "runtime" / "profile-api_only.json").read_text(encoding="utf-8")
    )
    local_profile = json.loads(
        (tmp_path / "local-capable" / "runtime" / "profile-local_capable.json").read_text(
            encoding="utf-8"
        )
    )
    approved_models = json.loads(
        (tmp_path / "local-capable" / "runtime" / "approved-models.json").read_text(
            encoding="utf-8"
        )
    )

    assert api_manifest.build_profile is BuildProfile.API_ONLY
    assert local_manifest.build_profile is BuildProfile.LOCAL_CAPABLE
    assert api_profile["available_runtime_modes"] == ["API_LLM"]
    assert api_profile["approved_model_manifest"] is None
    assert local_profile["available_runtime_modes"] == ["API_LLM", "LOCAL_GPU", "AUTO"]
    assert local_profile["approved_model_manifest"] == "runtime/approved-models.json"
    assert approved_models["models"][0]["model_id"] == "approved-model"
    assert not (tmp_path / "api-only" / "runtime" / "approved-models.json").exists()


def test_build_release_excludes_forbidden_runtime_artifacts(tmp_path: Path) -> None:
    frontend_dist = tmp_path / "frontend-dist"
    (frontend_dist / "assets").mkdir(parents=True)
    (frontend_dist / "index.html").write_text("<!doctype html><html></html>", encoding="utf-8")
    (frontend_dist / "assets" / "app.js").write_text("console.log('ui');", encoding="utf-8")

    build_release_from(
        profile=BuildProfile.LOCAL_CAPABLE,
        output_dir=tmp_path / "release",
        frontend_dist=frontend_dist,
    )

    forbidden_suffixes = {".map", ".pyc"}
    forbidden_names = {".env", "node.exe", "npm", "npm.cmd"}
    forbidden_path_parts = {"tests", "experiments", "__pycache__"}

    for path in (tmp_path / "release").rglob("*"):
        relative = path.relative_to(tmp_path / "release")
        assert not any(part in forbidden_path_parts for part in relative.parts)
        assert path.name not in forbidden_names
        if path.is_file():
            assert path.suffix not in forbidden_suffixes
