from pathlib import Path

import pytest

from google_work_agent.ports.llm.local_model_profile import (
    LocalInferenceClass,
    LocalModelProfileV1,
)

ROOT = Path(__file__).resolve().parents[3]


def test_product_local_profile__routes_all_prompts__to_single_release_model() -> None:
    profile = LocalModelProfileV1.from_bytes(
        (ROOT / "config/local-model-profile-v1.json").read_bytes()
    )

    assert profile.profile_id == "qwen3.5-9b-single-model-v1"
    assert profile.model_ids == ("qwen3.5:9b",)
    assert profile.model_id_for_prompt("request_understanding.identify_goal") == "qwen3.5:9b"
    assert profile.model_id_for_prompt("planning.compose_answer") == "qwen3.5:9b"
    assert profile.inference_class_for_prompt(
        "request_understanding.detect_ambiguity"
    ) is LocalInferenceClass.REASONING


def test_local_profile__rejects_duplicate__json_authority() -> None:
    with pytest.raises(ValueError, match="duplicate JSON key"):
        LocalModelProfileV1.from_bytes(
            b'{"schema_version":1,"schema_version":1}'
        )
