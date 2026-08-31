from __future__ import annotations

import pytest
from evaluation.contracts.product_episode_projection import ProductEpisodeE2EProjectionV1
from pydantic import ValidationError
from tests.evaluation.conftest import make_episode


def test_product_episode_keeps_decision_script_outside_product_input() -> None:
    episode = make_episode()

    assert isinstance(episode.product_input, dict)
    assert "decision_script" not in episode.product_input
    assert episode.evaluator_input.decision_script == ["APPROVAL:REJECT"]
    assert (
        ProductEpisodeE2EProjectionV1.model_validate_json(episode.canonical_json(), strict=True)
        == episode
    )


def test_product_episode_rejects_incompatible_version() -> None:
    payload = make_episode().model_dump(mode="json")
    payload["schema_version"] = 2

    with pytest.raises(ValidationError):
        ProductEpisodeE2EProjectionV1.model_validate(payload, strict=True)
