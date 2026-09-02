from google_work_agent.adapters.llm.gemini.runtime_status import GeminiLlmRuntimeStatusAdapter
from google_work_agent.adapters.llm.gemini.structured_inference import GeminiConnectionService


def test_gemini_status__leaf_fails__closed_without_transport() -> None:
    status = GeminiLlmRuntimeStatusAdapter("gemini", GeminiConnectionService(None)).get_status(
        api_key="secret", timeout_seconds=1
    )

    assert status.availability == "UNAVAILABLE"
    assert status.error_code == "API_PROVIDER_NOT_CONFIGURED"
