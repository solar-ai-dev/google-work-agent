from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from evaluation.reporting.write_results import (
    RESULT_FILENAMES,
    EvaluationResultSetV1,
    ResultWriteError,
    write_results,
)


def _result_set(*, status: str = "COMPLETE") -> EvaluationResultSetV1:
    return cast(
        EvaluationResultSetV1,
        EvaluationResultSetV1.model_validate(
            {
                "schema_version": 1,
                "experiment_manifest": {
                    "schema_version": 1,
                    "experiment_id": "EXP-001",
                    "run_status": status,
                    "evaluation_item_count": 1,
                    "completed_item_count": 1 if status == "COMPLETE" else 0,
                },
                "candidate_config": {"candidate_id": "candidate-1"},
                "config_diff": {"changes": {}},
                "evaluation_items": [{"evaluation_item_id": "item-1"}],
                "node_results": [],
                "trajectory_results": [],
                "grader_results": [],
                "case_failures": [],
                "summary_metrics": {"denominator": 1},
                "budget_report": {"cost_usd": 0.0},
                "human_review": "# Human review\n\nPENDING",
                "product_decision_record": "# Product decision\n\nDEFERRED",
            },
            strict=True,
        ),
    )


def test_result_writer_atomically_materializes_exact_set_and_hashes(tmp_path: Path) -> None:
    target = write_results(
        experiment_id="EXP-001",
        result_set=_result_set(),
        results_root=tmp_path,
    )

    assert {path.name for path in target.iterdir()} == set(RESULT_FILENAMES)
    manifest = json.loads((target / "experiment_manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["artifact_hashes"]) == set(RESULT_FILENAMES) - {"experiment_manifest.json"}
    assert not any(path.name.startswith(".EXP-001") for path in tmp_path.iterdir())


def test_result_writer_never_silently_overwrites_prior_results(tmp_path: Path) -> None:
    result_set = _result_set()
    write_results(experiment_id="EXP-001", result_set=result_set, results_root=tmp_path)

    with pytest.raises(ResultWriteError, match="already exists"):
        write_results(experiment_id="EXP-001", result_set=result_set, results_root=tmp_path)


def test_result_writer_rejects_sensitive_payload(tmp_path: Path) -> None:
    payload = _result_set().model_dump(mode="json")
    payload["candidate_config"]["access_token"] = "credential"
    unsafe = EvaluationResultSetV1.model_validate(payload, strict=True)

    with pytest.raises(ResultWriteError, match="sensitive field"):
        write_results(experiment_id="EXP-001", result_set=unsafe, results_root=tmp_path)
    assert not (tmp_path / "EXP-001").exists()


def test_complete_manifest_cannot_hide_unexecuted_items() -> None:
    payload = _result_set().model_dump(mode="json")
    payload["experiment_manifest"]["completed_item_count"] = 0

    with pytest.raises(ValueError, match="account for every"):
        EvaluationResultSetV1.model_validate(payload, strict=True)
