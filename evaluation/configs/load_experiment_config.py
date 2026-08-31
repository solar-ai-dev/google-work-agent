"""Strict loader for one checked-in current experiment config."""

from pathlib import Path
from typing import cast

from evaluation.contracts.evaluation_contract import load_strict_json
from evaluation.contracts.experiment_config import ExperimentConfigV1


def load_experiment_config(path: Path) -> ExperimentConfigV1:
    return cast(
        ExperimentConfigV1,
        ExperimentConfigV1.model_validate(
            load_strict_json(path.read_text(encoding="utf-8")), strict=True
        ),
    )


__all__ = ["load_experiment_config"]
