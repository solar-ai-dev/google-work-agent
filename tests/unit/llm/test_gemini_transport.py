"""Unit tests for the Gemini HTTP transport's fixed-sampling wiring
(docs/15 section 9.5, Runtime Prompt Activation Gate).

Mirrors tests/unit/llm/test_ollama_transport.py's sampling coverage. Gemini
support is temperature-only: this adapter's contract does not confirm the
generateContent API's seed support, so seed is never wired here (see
adapters/llm/gemini.py and adapters/llm/api_provider.py module comments).
"""

from __future__ import annotations

import json
from typing import cast
from urllib.request import Request

import pytest

from google_work_agent.adapters.llm.gemini.structured_inference import (
    GeminiStructuredInferenceAdapter,
)
from google_work_agent.adapters.llm.gemini.transport import GeminiHTTPClient
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
    RuntimePolicy,
)


class _HTTPResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _HTTPResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _request_body(request: Request) -> dict[str, object]:
    assert isinstance(request.data, bytes)
    return cast(dict[str, object], json.loads(request.data.decode("utf-8")))


def _prompt_ref() -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test-bundle",
        prompt_id="a.b",
        prompt_version="1",
        content_hash="hash",
        agent_role="test_role",
        subgraph_name="a",
        node_name="b",
        node_state="BASELINE",
        purpose="test",
        input_schema_version="v1",
        output_schema_version="v1",
    )


def _fake_response() -> bytes:
    return json.dumps(
        {
            "candidates": [
                {"content": {"parts": [{"text": "{}"}]}, "finishReason": "STOP"},
            ],
            "modelVersion": "gemini-flash-latest",
        }
    ).encode("utf-8")


def test_invoke_structured__omits_temperature_when__sampling_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production dispatch (sampling_temperature None) must produce the
    exact same generationConfig as before this change."""
    captured: list[Request] = []

    def fake_urlopen(request: Request, *, timeout: int) -> _HTTPResponse:
        del timeout
        captured.append(request)
        return _HTTPResponse(_fake_response())

    monkeypatch.setattr("google_work_agent.adapters.llm.gemini.transport.urlopen", fake_urlopen)

    GeminiHTTPClient().invoke_structured(
        model_id="gemini-flash-latest",
        prompt_ref=_prompt_ref(),
        prompt_input={},
        output_schema=OutputSchemaDefinition(schema_version="1", json_schema={}),
        timeout_seconds=5,
        api_key="test-key",
        instruction_text="You are a test assistant.",
    )

    sent_body = _request_body(captured[0])
    assert sent_body["generationConfig"] == {"responseMimeType": "application/json"}


def test_invoke_structured__sends_fixed__temperature_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Request] = []

    def fake_urlopen(request: Request, *, timeout: int) -> _HTTPResponse:
        del timeout
        captured.append(request)
        return _HTTPResponse(_fake_response())

    monkeypatch.setattr("google_work_agent.adapters.llm.gemini.transport.urlopen", fake_urlopen)

    GeminiHTTPClient().invoke_structured(
        model_id="gemini-flash-latest",
        prompt_ref=_prompt_ref(),
        prompt_input={},
        output_schema=OutputSchemaDefinition(schema_version="1", json_schema={}),
        timeout_seconds=5,
        api_key="test-key",
        instruction_text="You are a test assistant.",
        sampling_temperature=0.0,
    )

    sent_body = _request_body(captured[0])
    assert sent_body["generationConfig"] == {
        "responseMimeType": "application/json",
        "temperature": 0.0,
    }
    assert "seed" not in sent_body["generationConfig"]


def test_gemini_transport__never_accepts__a_seed_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GeminiHTTPClient.invoke_structured has no sampling_seed parameter at
    all -- there is no code path that could send an unconfirmed field."""
    import inspect

    signature = inspect.signature(GeminiHTTPClient.invoke_structured)
    assert "sampling_seed" not in signature.parameters


def test_provider_forwards_temperature__but_never_seed__to_gemini_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Request] = []

    def fake_urlopen(request: Request, *, timeout: int) -> _HTTPResponse:
        del timeout
        captured.append(request)
        return _HTTPResponse(_fake_response())

    monkeypatch.setattr("google_work_agent.adapters.llm.gemini.transport.urlopen", fake_urlopen)

    provider = GeminiStructuredInferenceAdapter(
        provider_name="gemini",
        transport=GeminiHTTPClient(),
        model="gemini-flash-latest",
    )

    provider.invoke_structured(
        prompt_ref=_prompt_ref(),
        prompt_input={},
        output_schema=OutputSchemaDefinition(schema_version="1", json_schema={}),
        runtime_policy=RuntimePolicy(sampling_temperature=0.0, sampling_seed=7),
        api_key="test-key",
    )

    sent_body = _request_body(captured[0])
    generation_config = cast(dict[str, object], sent_body["generationConfig"])
    assert generation_config["temperature"] == 0.0
    assert "seed" not in generation_config
    assert "seed" not in sent_body


def test_provider_omits_temperature__when_runtime_policy__leaves_sampling_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pins the production path: a bare ``RuntimePolicy()`` (what
    api/composition.py always constructs) must never add a temperature key."""
    captured: list[Request] = []

    def fake_urlopen(request: Request, *, timeout: int) -> _HTTPResponse:
        del timeout
        captured.append(request)
        return _HTTPResponse(_fake_response())

    monkeypatch.setattr("google_work_agent.adapters.llm.gemini.transport.urlopen", fake_urlopen)

    provider = GeminiStructuredInferenceAdapter(
        provider_name="gemini",
        transport=GeminiHTTPClient(),
        model="gemini-flash-latest",
    )

    provider.invoke_structured(
        prompt_ref=_prompt_ref(),
        prompt_input={},
        output_schema=OutputSchemaDefinition(schema_version="1", json_schema={}),
        runtime_policy=RuntimePolicy(),
        api_key="test-key",
    )

    sent_body = _request_body(captured[0])
    assert sent_body["generationConfig"] == {"responseMimeType": "application/json"}
