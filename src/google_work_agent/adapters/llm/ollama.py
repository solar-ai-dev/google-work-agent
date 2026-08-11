"""Loopback-only Ollama adapter and probe transport."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from google_work_agent.ports import (
    ActualRuntime,
    AvailabilityState,
    OutputSchemaDefinition,
    ProbeResult,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
    StructuredLLMProvider,
)


class OllamaTransport(Protocol):
    def probe(self, *, endpoint: str, model_id: str | None, timeout_seconds: int) -> ProbeResult:
        raise NotImplementedError

    def invoke_structured(
        self,
        *,
        endpoint: str,
        model_id: str,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        timeout_seconds: int,
        instruction_text: str,
        sampling_temperature: float | None = None,
        sampling_seed: int | None = None,
    ) -> ProviderResponsePayload:
        raise NotImplementedError


def _no_instruction_text(prompt_ref: PromptReference) -> str:
    del prompt_ref
    return ""


@dataclass(frozen=True, slots=True)
class OllamaStructuredLLMProvider(StructuredLLMProvider):
    """Dispatches one structured Ollama call.

    ``resolve_instruction_text`` is called here, immediately before dispatch,
    and its result lives only as a local variable for the duration of this
    call -- it is never attached to ``prompt_ref`` (which flows into
    ``AgentLocalStateV1``/trace_context/LangGraph checkpoints via
    ``prompt_ref_to_mapping``) or returned to any caller. This keeps the
    assembled prompt text out of Trace/Checkpoint storage per
    docs/00-CODE-AGENT-START-HERE.md section 4.
    """

    provider_name: str
    transport: OllamaTransport
    endpoint: str
    model_id: str
    runtime: ActualRuntime = ActualRuntime.LOCAL_GPU
    resolve_instruction_text: Callable[[PromptReference], str] = field(
        default=_no_instruction_text
    )

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        runtime_policy: RuntimePolicy,
        api_key: str | None,
    ) -> ProviderResponsePayload:
        del api_key
        instruction_text = self.resolve_instruction_text(prompt_ref)
        return self.transport.invoke_structured(
            endpoint=self.endpoint,
            model_id=self.model_id,
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            output_schema=output_schema,
            timeout_seconds=runtime_policy.local_timeout_seconds,
            instruction_text=instruction_text,
            sampling_temperature=runtime_policy.sampling_temperature,
            sampling_seed=runtime_policy.sampling_seed,
        )


class OllamaHTTPClient(OllamaTransport):
    """Minimal stdlib HTTP client for local loopback Ollama."""

    def probe(self, *, endpoint: str, model_id: str | None, timeout_seconds: int) -> ProbeResult:
        _validate_loopback_endpoint(endpoint)
        try:
            # Ollama's /api/version and /api/tags are read-only GET endpoints;
            # POSTing to them returns 405 (confirmed against a live Ollama
            # instance), which this probe was misreporting as OLLAMA_UNAVAILABLE.
            version = _get_json(
                endpoint=endpoint,
                path="/api/version",
                timeout_seconds=timeout_seconds,
            )
            models = _get_json(
                endpoint=endpoint,
                path="/api/tags",
                timeout_seconds=timeout_seconds,
            )
        except TimeoutError:
            return ProbeResult(
                availability=AvailabilityState.UNAVAILABLE,
                safe_error_code="TIMEOUT",
            )
        except (HTTPError, URLError, ValueError):
            return ProbeResult(
                availability=AvailabilityState.UNAVAILABLE,
                safe_error_code="OLLAMA_UNAVAILABLE",
            )
        raw_models = models.get("models", [])
        model_items = raw_models if isinstance(raw_models, list) else []
        model_names = {
            str(item.get("name"))
            for item in model_items
            if isinstance(item, dict) and "name" in item
        }
        if model_id and model_id not in model_names:
            return ProbeResult(
                availability=AvailabilityState.DEGRADED,
                safe_error_code="MODEL_NOT_FOUND",
                metadata={"version": version.get("version"), "model_present": False},
            )
        return ProbeResult(
            availability=AvailabilityState.AVAILABLE,
            last_probe_at_ms=None,
            metadata={
                "version": version.get("version"),
                "model_present": True if model_id else None,
            },
        )

    def invoke_structured(
        self,
        *,
        endpoint: str,
        model_id: str,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        timeout_seconds: int,
        instruction_text: str,
        sampling_temperature: float | None = None,
        sampling_seed: int | None = None,
    ) -> ProviderResponsePayload:
        _validate_loopback_endpoint(endpoint)
        payload: dict[str, object] = {
            "model": model_id,
            "system": instruction_text,
            "prompt": json.dumps(
                {
                    "prompt_ref": {
                        "prompt_id": prompt_ref.prompt_id,
                        "prompt_version": prompt_ref.prompt_version,
                        "content_hash": prompt_ref.content_hash,
                    },
                    "input": prompt_input,
                },
                sort_keys=True,
            ),
            "stream": False,
            "format": dict(output_schema.json_schema),
        }
        # docs/15 section 9.5 (Runtime Prompt Activation Gate): "options" is
        # Ollama's documented /api/generate sampling-parameter object. Only
        # sent when the caller (the Gate Runner) explicitly fixes sampling
        # conditions -- omitted entirely otherwise, so production dispatch
        # (which never sets these) produces the exact same payload as before.
        options: dict[str, object] = {}
        if sampling_temperature is not None:
            options["temperature"] = sampling_temperature
        if sampling_seed is not None:
            options["seed"] = sampling_seed
        if options:
            payload["options"] = options
        response = _post_json(
            endpoint=endpoint,
            path="/api/generate",
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        content = response.get("response", "{}")
        return ProviderResponsePayload(
            content=content,
            model=str(response.get("model", model_id)),
            provider_request_id=None,
            input_tokens=_optional_int(response.get("prompt_eval_count")),
            output_tokens=_optional_int(response.get("eval_count")),
            latency_ms=_optional_int(response.get("total_duration")) or 0,
            estimated_cost_usd=None,
        )


def _get_json(
    *,
    endpoint: str,
    path: str,
    timeout_seconds: int,
) -> dict[str, object]:
    url = endpoint.rstrip("/") + path
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("invalid Ollama response")
            return cast(dict[str, object], payload)
    except TimeoutError:
        raise
    except HTTPError:
        raise
    except URLError:
        raise


def _post_json(
    *,
    endpoint: str,
    path: str,
    payload: Mapping[str, object],
    timeout_seconds: int,
) -> dict[str, object]:
    url = endpoint.rstrip("/") + path
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("invalid Ollama response")
            return cast(dict[str, object], payload)
    except TimeoutError:
        raise
    except HTTPError:
        raise
    except URLError:
        raise
    except json.JSONDecodeError as error:
        raise ValueError("invalid Ollama response") from error


def _validate_loopback_endpoint(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Ollama endpoint must stay on loopback")
    if parsed.port is None:
        raise ValueError("Ollama endpoint must include an explicit port")


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
