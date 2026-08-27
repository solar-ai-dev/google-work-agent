from google_work_agent.adapters.llm.ollama.runtime_status import OllamaLlmRuntimeStatusAdapter


class _Probe:
    def probe(self, **kwargs: object) -> object:
        raise AssertionError(f"disabled status must not probe: {kwargs}")


def test_ollama_status_leaf_is_disabled_without_endpoint_and_model() -> None:
    status = OllamaLlmRuntimeStatusAdapter(_Probe()).get_status(  # type: ignore[arg-type]
        endpoint=None,
        model=None,
    )

    assert status.availability == "DISABLED"
    assert status.error_code == "LOCAL_RUNTIME_NOT_CONFIGURED"
