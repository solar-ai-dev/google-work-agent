from google_work_agent.application.use_cases.llm_credential.store_llm_credential import (
    StoreLlmCredentialHandler,
)


def test_store_llm_credential__has_exact__application_owner() -> None:
    assert (
        StoreLlmCredentialHandler.__module__
        == "google_work_agent.application.use_cases.llm_credential.store_llm_credential"
    )
    assert StoreLlmCredentialHandler.__name__ == "StoreLlmCredentialHandler"
