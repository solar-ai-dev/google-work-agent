from __future__ import annotations

from collections.abc import Mapping

import pytest

from google_work_agent.application.agents.planning.outline_answer import outline_answer


def test_outline_uses__distinct_prompt__and_minimum_projection() -> None:
    captured: dict[str, object] = {}

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        captured.update({"prompt_id": prompt_id, "prompt_input": dict(prompt_input)})
        return {"sections": ["Conclusion", "Uncertainty"], "evidence_refs": ["e1"]}

    result = outline_answer(
        user_request="Summarize the current facts.",
        request_intent={"goal": "summary"},
        work_analysis={"action_necessity": "NOT_REQUIRED"},
        evidence=[{"evidence_id": "e1", "excerpt": "fact"}],
        invoke=invoke,
    )

    assert result == {"sections": ["Conclusion", "Uncertainty"], "evidence_refs": ["e1"]}
    assert captured["prompt_id"] == "planning.outline_answer"
    prompt_input = captured["prompt_input"]
    assert isinstance(prompt_input, dict)
    assert set(prompt_input) == {
        "user_request",
        "request_intent",
        "work_analysis",
        "evidence",
    }


def test_outline_rejects__evidence_outside__current_projection() -> None:
    with pytest.raises(ValueError, match="outside"):
        outline_answer(
            user_request="Summarize.",
            request_intent={"goal": "summary"},
            work_analysis=None,
            evidence=[],
            invoke=lambda _prompt_id, _prompt_input: {
                "sections": ["Conclusion"],
                "evidence_refs": ["previous-run"],
            },
        )
