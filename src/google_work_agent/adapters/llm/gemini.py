"""Google Gemini adapter -- the real API_LLM baseline transport.

Mirrors ``adapters/llm/ollama.py``'s shape (stdlib-only HTTP client behind
the provider's transport Protocol, ``instruction_text`` resolved as a
memory-only local variable immediately before dispatch -- never attached to
``PromptReference``/Trace/Checkpoint, per
docs/00-CODE-AGENT-START-HERE.md section 4).

``output_schema`` is intentionally NOT translated into Gemini's
``responseSchema`` (an OpenAPI 3.0 Schema subset): this repository's real
schemas (``experiments/datasets/google_workspace/schemas/*.schema.json`` and
the production ``OutputSchemaDefinition.json_schema`` values) use JSON
Schema draft shapes such as ``"type": ["string", "null"]`` nullable unions
that ``responseSchema`` cannot represent. Writing a lossy translator would
mean grading against something other than the real schema. Instead, only
``responseMimeType: application/json`` is requested (guarantees syntactically
valid JSON), and structural correctness is graded post-hoc against the real
schema exactly the same way for every provider (``jsonschema.validate`` in
the Gate Runner; ``_validate_or_repair`` in ``application/llm.py`` for
production dispatch) -- no relaxed criterion, just no invented translation.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from google_work_agent.ports import (
    AvailabilityState,
    OutputSchemaDefinition,
    ProbeResult,
    PromptReference,
    ProviderResponsePayload,
)

DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
# "gemini-2.5-flash" still exists in GET /v1beta/models but returns 404 on
# :generateContent for this project ("no longer available to new users").
# "-latest" is Google's own forward-compatible alias for exactly this
# deprecation pattern, verified live against the real API (2026-08-10):
# a direct :generateContent call returned 200 with a normal candidate.
DEFAULT_GEMINI_MODEL_ID = "gemini-flash-latest"
_MIN_RETRY_DELAY_SECONDS = 1.0
_MAX_RETRY_DELAY_SECONDS = 60.0


class GeminiHTTPClient:
    """Minimal stdlib HTTP client for the real Gemini ``generateContent`` API."""

    def __init__(self, *, base_url: str = DEFAULT_GEMINI_BASE_URL) -> None:
        self._base_url = base_url.rstrip("/")

    def probe(self, *, api_key: str, timeout_seconds: int) -> ProbeResult:
        if not api_key:
            return ProbeResult(
                availability=AvailabilityState.NOT_CONFIGURED,
                safe_error_code="API_KEY_MISSING",
            )
        request = Request(
            f"{self._base_url}/models",
            headers={"x-goog-api-key": api_key, "Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                response.read()
        except TimeoutError:
            return ProbeResult(
                availability=AvailabilityState.UNAVAILABLE,
                safe_error_code="TIMEOUT",
            )
        except HTTPError as error:
            if error.code in (401, 403):
                return ProbeResult(
                    availability=AvailabilityState.NOT_CONFIGURED,
                    safe_error_code="API_KEY_INVALID",
                )
            if error.code == 429:
                return ProbeResult(
                    availability=AvailabilityState.DEGRADED,
                    safe_error_code="RATE_LIMITED",
                )
            return ProbeResult(
                availability=AvailabilityState.UNAVAILABLE,
                safe_error_code="API_PROVIDER_UNAVAILABLE",
            )
        except URLError:
            return ProbeResult(
                availability=AvailabilityState.UNAVAILABLE,
                safe_error_code="API_PROVIDER_UNAVAILABLE",
            )
        return ProbeResult(availability=AvailabilityState.AVAILABLE)

    def invoke_structured(
        self,
        *,
        model_id: str,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        timeout_seconds: int,
        api_key: str,
        instruction_text: str,
        sampling_temperature: float | None = None,
    ) -> ProviderResponsePayload:
        del output_schema  # see module docstring: graded post-hoc, not translated here
        generation_config: dict[str, object] = {"responseMimeType": "application/json"}
        # docs/15 section 9.5 (Runtime Prompt Activation Gate): "temperature"
        # is a documented generationConfig field. Only sent when the caller
        # (the Gate Runner) explicitly fixes sampling conditions -- omitted
        # entirely otherwise, so production dispatch (which never sets this)
        # produces the exact same request body as before. "seed" is
        # deliberately not wired here: this adapter's contract does not
        # confirm the generateContent API used here supports it, and an
        # unconfirmed field must not be sent.
        if sampling_temperature is not None:
            generation_config["temperature"] = sampling_temperature
        body = {
            "systemInstruction": {"parts": [{"text": instruction_text}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "prompt_ref": {
                                        "prompt_id": prompt_ref.prompt_id,
                                        "prompt_version": prompt_ref.prompt_version,
                                        "content_hash": prompt_ref.content_hash,
                                    },
                                    "input": prompt_input,
                                },
                                sort_keys=True,
                            )
                        }
                    ],
                }
            ],
            "generationConfig": generation_config,
        }
        request = Request(
            f"{self._base_url}/models/{model_id}:generateContent",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            method="POST",
        )
        raw = _post_with_rate_limit_backoff(request, timeout_seconds=timeout_seconds)
        if not isinstance(raw, dict):
            raise ValueError("invalid Gemini response")
        text = _extract_text(raw)
        usage = raw.get("usageMetadata")
        usage = usage if isinstance(usage, dict) else {}
        return ProviderResponsePayload(
            content=text,
            model=str(raw.get("modelVersion", model_id)),
            provider_request_id=None,
            input_tokens=_optional_int(usage.get("promptTokenCount")),
            output_tokens=_optional_int(usage.get("candidatesTokenCount")),
            latency_ms=0,
            estimated_cost_usd=None,
        )


def _post_with_rate_limit_backoff(request: Request, *, timeout_seconds: int) -> object:
    """POST with bounded backoff on 429 so free-tier RPM limits don't get
    graded as real model-quality failures (see module docstring: grading
    must reflect the real schema/model, not infra noise). Retries only
    within ``timeout_seconds`` -- the same API_LLM call budget every other
    caller respects -- then gives up by raising ``TimeoutError``, which
    ``application/llm.py::_invoke_provider`` already maps to
    ``LLMErrorCode.PROVIDER_TIMEOUT`` (retryable).
    """
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        try:
            with urlopen(request, timeout=max(1, int(remaining))) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code != 429:
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    "Gemini rate limit (429) did not clear within the API call budget"
                ) from error
            delay = _parse_retry_delay_seconds(error) or _MIN_RETRY_DELAY_SECONDS
            time.sleep(min(delay, remaining, _MAX_RETRY_DELAY_SECONDS))


def _parse_retry_delay_seconds(error: HTTPError) -> float | None:
    retry_after = error.headers.get("Retry-After") if error.headers is not None else None
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass
    try:
        body = json.loads(error.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    details = body.get("error", {})
    details = details.get("details", []) if isinstance(details, dict) else []
    for detail in details if isinstance(details, list) else []:
        if not isinstance(detail, dict):
            continue
        raw_delay = detail.get("retryDelay")
        if isinstance(raw_delay, str) and raw_delay.endswith("s"):
            try:
                return float(raw_delay[:-1])
            except ValueError:
                continue
    return None


def _extract_text(raw: dict[str, object]) -> str:
    candidates = raw.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        feedback = raw.get("promptFeedback")
        block_reason = feedback.get("blockReason") if isinstance(feedback, dict) else None
        if block_reason is not None:
            raise ValueError(f"Gemini blocked the request: {block_reason}")
        raise ValueError("Gemini response had no candidates")
    first = candidates[0]
    if not isinstance(first, dict):
        raise ValueError("invalid Gemini candidate")
    content = first.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list) or not parts or not isinstance(parts[0], dict):
        finish_reason = first.get("finishReason")
        raise ValueError(f"Gemini response had no content parts (finishReason={finish_reason!r})")
    text = parts[0].get("text")
    if not isinstance(text, str):
        raise ValueError("Gemini response part had no text")
    return text


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
