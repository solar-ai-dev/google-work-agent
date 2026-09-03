from google_work_agent.application.use_cases.llm_credential.get_llm_credential_status import (
    GetLlmCredentialStatusHandler,
)


def test_get_llm_credential_status__has_exact__application_owner() -> None:
    assert (
        GetLlmCredentialStatusHandler.__module__
        == "google_work_agent.application.use_cases.llm_credential.get_llm_credential_status"
    )
    assert GetLlmCredentialStatusHandler.__name__ == "GetLlmCredentialStatusHandler"
