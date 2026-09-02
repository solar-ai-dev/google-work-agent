from google_work_agent.adapters.llm.ollama.runtime_status import OllamaLlmRuntimeStatusAdapter
from google_work_agent.adapters.llm.probes import LoopbackOllamaProbe
from google_work_agent.ports.llm.structured_inference_contracts import (
    ApprovedModelInfo,
    AvailabilityState,
    ProbeResult,
)


class _Probe:
    def probe(self, **kwargs: object) -> object:
        raise AssertionError(f"disabled status must not probe: {kwargs}")


def test_ollama_status_leaf__is_disabled_without__endpoint_and_model() -> None:
    status = OllamaLlmRuntimeStatusAdapter(_Probe()).get_status(  # type: ignore[arg-type]
        endpoint=None,
        model=None,
    )

    assert status.availability == "DISABLED"
    assert status.error_code == "LOCAL_RUNTIME_NOT_CONFIGURED"


class _AvailableTransport:
    def __init__(self, *, version: str, digest: str) -> None:
        self.version = version
        self.digest = digest

    def probe(self, **kwargs: object) -> ProbeResult:
        del kwargs
        return ProbeResult(
            availability=AvailabilityState.AVAILABLE,
            metadata={"version": self.version, "model_digest": self.digest},
        )


def _approved_model() -> ApprovedModelInfo:
    return ApprovedModelInfo(
        model_id="qwen2.5:7b",
        runtime="OLLAMA",
        manifest_version="1",
        schema_version="1",
        minimum_runtime_version="0.6.0",
        digest="a" * 64,
    )


def test_ollama_probe_accepts__exact_signed_model__hash_and_minimum_version() -> None:
    result = LoopbackOllamaProbe(
        _AvailableTransport(version="0.6.2", digest="sha256:" + "a" * 64)  # type: ignore[arg-type]
    ).probe(endpoint="http://127.0.0.1:11434", approved_model=_approved_model())

    assert result.availability is AvailabilityState.AVAILABLE


def test_ollama_probe__rejects_model__hash_mismatch() -> None:
    result = LoopbackOllamaProbe(
        _AvailableTransport(version="0.6.2", digest="sha256:" + "b" * 64)  # type: ignore[arg-type]
    ).probe(endpoint="http://127.0.0.1:11434", approved_model=_approved_model())

    assert result.availability is AvailabilityState.DEGRADED
    assert result.safe_error_code == "MODEL_HASH_MISMATCH"


def test_ollama_probe__rejects_unsupported__runtime_version() -> None:
    result = LoopbackOllamaProbe(
        _AvailableTransport(version="0.5.9", digest="sha256:" + "a" * 64)  # type: ignore[arg-type]
    ).probe(endpoint="http://127.0.0.1:11434", approved_model=_approved_model())

    assert result.availability is AvailabilityState.DEGRADED
    assert result.safe_error_code == "OLLAMA_VERSION_UNSUPPORTED"
