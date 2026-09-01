from __future__ import annotations

from pathlib import Path

import pytest
from evaluation.configs.load_experiment_config import load_experiment_config
from evaluation.fixtures.load_current_fixture import current_fixture_root_hash
from evaluation.runner.verify_product_identity import verify_product_identity


def test_current_corrective_config_is_strict_and_target_bound() -> None:
    config = load_experiment_config(Path("evaluation/configs/EXP-165-CORRECTIVE-MAIN.json"))
    assert config.target.target_kind == "MAIN_PROFILE"
    assert config.target.target_id == "single_baseline"
    assert config.grader_version == "0.5"
    assert config.adoption_criteria["automated_release"] is False
    assert config.fixture_snapshot_hash == current_fixture_root_hash()
    identity = verify_product_identity(config)
    assert identity.product_commit_sha == config.product_commit_sha
    assert identity.prompt_bundle_version == config.prompt_bundle_version


def test_config_rejects_unknown_fields(tmp_path: Path) -> None:
    source = Path("evaluation/configs/EXP-165-CORRECTIVE-MAIN.json").read_text(encoding="utf-8")
    path = tmp_path / "bad.json"
    path.write_text(
        source.replace('"schema_version": 1,', '"schema_version": 1, "gold": true,', 1),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_experiment_config(path)
