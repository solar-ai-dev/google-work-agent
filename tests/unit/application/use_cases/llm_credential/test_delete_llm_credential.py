from google_work_agent.application.use_cases.llm_credential.delete_llm_credential import (
    DeleteLlmCredentialHandler,
)


def test_delete_llm_credential__has_exact__application_owner() -> None:
    assert (
        DeleteLlmCredentialHandler.__module__
        == "google_work_agent.application.use_cases.llm_credential.delete_llm_credential"
    )
    assert DeleteLlmCredentialHandler.__name__ == "DeleteLlmCredentialHandler"
