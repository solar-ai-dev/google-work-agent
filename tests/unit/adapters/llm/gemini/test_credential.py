from google_work_agent.adapters.llm.gemini.credential import GeminiLlmCredentialAdapter
from google_work_agent.adapters.llm.runtime.llm_credential_router import SessionMemorySecretStore


def test_gemini_credential_leaf__replays_same_operation__without_secret_projection() -> None:
    store = SessionMemorySecretStore()
    adapter = GeminiLlmCredentialAdapter("gemini", "TEST", None, store)

    first = adapter.store(b"secret", "SESSION_ONLY", "operation-1")
    replay = adapter.store(b"secret", "SESSION_ONLY", "operation-1")

    assert first == replay
    assert first.configured is True
    assert "secret" not in repr(first)
    assert adapter.reconcile("operation-1", "CONFIGURED", "SESSION_ONLY").status == "COMPLETED"
