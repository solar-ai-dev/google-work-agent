"""Unit tests for the Ollama HTTP transport (probe + invoke_structured).

Regression coverage for a bug where the availability probe POSTed to
Ollama's /api/version and /api/tags endpoints. Both are GET-only in Ollama's
real REST API (confirmed against a live `ollama serve` instance: POST
returns 405), so the probe always reported OLLAMA_UNAVAILABLE even when
Ollama was running and the model was installed.
"""

from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from google_work_agent.adapters.llm.ollama import OllamaHTTPClient, OllamaStructuredLLMProvider
from google_work_agent.ports import (
    AvailabilityState,
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


def test_probe_uses_get_for_version_and_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[Request] = []
    responses = [
        json.dumps({"version": "0.32.6"}).encode("utf-8"),
        json.dumps({"models": [{"name": "qwen2.5:3b"}]}).encode("utf-8"),
    ]

    def fake_urlopen(request: Request, *, timeout: int) -> _HTTPResponse:
        del timeout
        requests.append(request)
        return _HTTPResponse(responses.pop(0))

    monkeypatch.setattr("google_work_agent.adapters.llm.ollama.urlopen", fake_urlopen)

    result = OllamaHTTPClient().probe(
        endpoint="http://127.0.0.1:11434", model_id="qwen2.5:3b", timeout_seconds=5
    )

    assert [request.get_method() for request in requests] == ["GET", "GET"]
    assert [request.full_url for request in requests] == [
        "http://127.0.0.1:11434/api/version",
        "http://127.0.0.1:11434/api/tags",
    ]
    assert result.availability is AvailabilityState.AVAILABLE
    assert result.metadata["version"] == "0.32.6"


def test_probe_reports_model_not_found_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        json.dumps({"version": "0.32.6"}).encode("utf-8"),
        json.dumps({"models": [{"name": "other-model"}]}).encode("utf-8"),
    ]
    monkeypatch.setattr(
        "google_work_agent.adapters.llm.ollama.urlopen",
        lambda request, *, timeout: _HTTPResponse(responses.pop(0)),
    )

    result = OllamaHTTPClient().probe(
        endpoint="http://127.0.0.1:11434", model_id="qwen2.5:3b", timeout_seconds=5
    )

    assert result.availability is AvailabilityState.DEGRADED
    assert result.safe_error_code == "MODEL_NOT_FOUND"


def test_probe_reports_unavailable_on_real_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_405(request: Request, *, timeout: int) -> _HTTPResponse:
        del request, timeout
        raise HTTPError(
            "http://127.0.0.1:11434/api/version", 405, "method not allowed", None, BytesIO(b"")
        )

    monkeypatch.setattr("google_work_agent.adapters.llm.ollama.urlopen", raise_405)

    result = OllamaHTTPClient().probe(
        endpoint="http://127.0.0.1:11434", model_id="qwen2.5:3b", timeout_seconds=5
    )

    assert result.availability is AvailabilityState.UNAVAILABLE
    assert result.safe_error_code == "OLLAMA_UNAVAILABLE"


def test_invoke_structured_still_posts_to_generate(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[Request] = []

    def fake_urlopen(request: Request, *, timeout: int) -> _HTTPResponse:
        del timeout
        captured.append(request)
        return _HTTPResponse(json.dumps({"response": "{}", "model": "qwen2.5:3b"}).encode("utf-8"))

    monkeypatch.setattr("google_work_agent.adapters.llm.ollama.urlopen", fake_urlopen)

    OllamaHTTPClient().invoke_structured(
        endpoint="http://127.0.0.1:11434",
        model_id="qwen2.5:3b",
        prompt_ref=PromptReference(
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
        ),
        prompt_input={},
        output_schema=OutputSchemaDefinition(schema_version="1", json_schema={}),
        timeout_seconds=5,
        instruction_text="You are a test assistant.",
    )

    assert len(captured) == 1
    assert captured[0].get_method() == "POST"
    assert captured[0].full_url == "http://127.0.0.1:11434/api/generate"
    sent_body = json.loads(captured[0].data.decode("utf-8"))
    assert sent_body["system"] == "You are a test assistant."


def _prompt_ref_for_sampling_tests() -> PromptReference:
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


def test_invoke_structured_omits_options_when_sampling_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """docs/15 section 9.5: production dispatch (sampling_temperature/seed
    both None) must produce the exact same payload as before this change --
    no "options" key at all."""
    captured: list[Request] = []

    def fake_urlopen(request: Request, *, timeout: int) -> _HTTPResponse:
        del timeout
        captured.append(request)
        return _HTTPResponse(json.dumps({"response": "{}", "model": "qwen2.5:3b"}).encode("utf-8"))

    monkeypatch.setattr("google_work_agent.adapters.llm.ollama.urlopen", fake_urlopen)

    OllamaHTTPClient().invoke_structured(
        endpoint="http://127.0.0.1:11434",
        model_id="qwen2.5:3b",
        prompt_ref=_prompt_ref_for_sampling_tests(),
        prompt_input={},
        output_schema=OutputSchemaDefinition(schema_version="1", json_schema={}),
        timeout_seconds=5,
        instruction_text="You are a test assistant.",
    )

    sent_body = json.loads(captured[0].data.decode("utf-8"))
    assert "options" not in sent_body


def test_invoke_structured_sends_fixed_temperature_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Request] = []

    def fake_urlopen(request: Request, *, timeout: int) -> _HTTPResponse:
        del timeout
        captured.append(request)
        return _HTTPResponse(json.dumps({"response": "{}", "model": "qwen2.5:3b"}).encode("utf-8"))

    monkeypatch.setattr("google_work_agent.adapters.llm.ollama.urlopen", fake_urlopen)

    OllamaHTTPClient().invoke_structured(
        endpoint="http://127.0.0.1:11434",
        model_id="qwen2.5:3b",
        prompt_ref=_prompt_ref_for_sampling_tests(),
        prompt_input={},
        output_schema=OutputSchemaDefinition(schema_version="1", json_schema={}),
        timeout_seconds=5,
        instruction_text="You are a test assistant.",
        sampling_temperature=0.0,
    )

    sent_body = json.loads(captured[0].data.decode("utf-8"))
    assert sent_body["options"] == {"temperature": 0.0}


def test_invoke_structured_sends_fixed_seed_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[Request] = []

    def fake_urlopen(request: Request, *, timeout: int) -> _HTTPResponse:
        del timeout
        captured.append(request)
        return _HTTPResponse(json.dumps({"response": "{}", "model": "qwen2.5:3b"}).encode("utf-8"))

    monkeypatch.setattr("google_work_agent.adapters.llm.ollama.urlopen", fake_urlopen)

    OllamaHTTPClient().invoke_structured(
        endpoint="http://127.0.0.1:11434",
        model_id="qwen2.5:3b",
        prompt_ref=_prompt_ref_for_sampling_tests(),
        prompt_input={},
        output_schema=OutputSchemaDefinition(schema_version="1", json_schema={}),
        timeout_seconds=5,
        instruction_text="You are a test assistant.",
        sampling_temperature=0.0,
        sampling_seed=7,
    )

    sent_body = json.loads(captured[0].data.decode("utf-8"))
    assert sent_body["options"] == {"temperature": 0.0, "seed": 7}


def test_provider_forwards_runtime_policy_sampling_fields_to_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Request] = []

    def fake_urlopen(request: Request, *, timeout: int) -> _HTTPResponse:
        del timeout
        captured.append(request)
        return _HTTPResponse(json.dumps({"response": "{}", "model": "qwen2.5:3b"}).encode("utf-8"))

    monkeypatch.setattr("google_work_agent.adapters.llm.ollama.urlopen", fake_urlopen)

    provider = OllamaStructuredLLMProvider(
        provider_name="ollama",
        transport=OllamaHTTPClient(),
        endpoint="http://127.0.0.1:11434",
        model_id="qwen2.5:3b",
    )

    provider.invoke_structured(
        prompt_ref=_prompt_ref_for_sampling_tests(),
        prompt_input={},
        output_schema=OutputSchemaDefinition(schema_version="1", json_schema={}),
        runtime_policy=RuntimePolicy(sampling_temperature=0.0, sampling_seed=7),
        api_key=None,
    )

    sent_body = json.loads(captured[0].data.decode("utf-8"))
    assert sent_body["options"] == {"temperature": 0.0, "seed": 7}


def test_provider_omits_options_when_runtime_policy_leaves_sampling_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pins the production path: a bare ``RuntimePolicy()`` (what
    launcher/dev.py always constructs) must never add an "options" key."""
    captured: list[Request] = []

    def fake_urlopen(request: Request, *, timeout: int) -> _HTTPResponse:
        del timeout
        captured.append(request)
        return _HTTPResponse(json.dumps({"response": "{}", "model": "qwen2.5:3b"}).encode("utf-8"))

    monkeypatch.setattr("google_work_agent.adapters.llm.ollama.urlopen", fake_urlopen)

    provider = OllamaStructuredLLMProvider(
        provider_name="ollama",
        transport=OllamaHTTPClient(),
        endpoint="http://127.0.0.1:11434",
        model_id="qwen2.5:3b",
    )

    provider.invoke_structured(
        prompt_ref=_prompt_ref_for_sampling_tests(),
        prompt_input={},
        output_schema=OutputSchemaDefinition(schema_version="1", json_schema={}),
        runtime_policy=RuntimePolicy(),
        api_key=None,
    )

    sent_body = json.loads(captured[0].data.decode("utf-8"))
    assert "options" not in sent_body


def test_provider_resolves_instruction_text_only_as_a_local_call_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``PromptReference`` must never carry instruction text.

    ``prompt_ref_to_mapping`` (adapters/langgraph/agent_kernel.py) is the
    only path that turns a PromptReference into persisted AgentLocalState /
    trace_context / LangGraph checkpoint data, and it enumerates safe fields
    explicitly. Keeping instruction text off the PromptReference dataclass
    entirely -- resolved fresh as a local variable right before dispatch --
    means there is no field for a future edit to that mapping to
    accidentally start leaking.
    """

    prompt_ref = PromptReference(
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
    assert not hasattr(prompt_ref, "instruction_text")

    captured: list[Request] = []
    resolve_calls: list[str] = []

    def fake_urlopen(request: Request, *, timeout: int) -> _HTTPResponse:
        del timeout
        captured.append(request)
        return _HTTPResponse(json.dumps({"response": "{}", "model": "qwen2.5:3b"}).encode("utf-8"))

    monkeypatch.setattr("google_work_agent.adapters.llm.ollama.urlopen", fake_urlopen)

    def resolve_instruction_text(ref: PromptReference) -> str:
        resolve_calls.append(ref.prompt_id)
        return "Resolved instructions for " + ref.prompt_id

    provider = OllamaStructuredLLMProvider(
        provider_name="ollama",
        transport=OllamaHTTPClient(),
        endpoint="http://127.0.0.1:11434",
        model_id="qwen2.5:3b",
        resolve_instruction_text=resolve_instruction_text,
    )

    provider.invoke_structured(
        prompt_ref=prompt_ref,
        prompt_input={},
        output_schema=OutputSchemaDefinition(schema_version="1", json_schema={}),
        runtime_policy=RuntimePolicy(),
        api_key=None,
    )

    assert resolve_calls == ["a.b"]
    sent_body = json.loads(captured[0].data.decode("utf-8"))
    assert sent_body["system"] == "Resolved instructions for a.b"
