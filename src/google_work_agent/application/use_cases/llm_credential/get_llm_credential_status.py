"""Read token-free LLM credential status."""

from dataclasses import dataclass

from google_work_agent.ports.llm.llm_credential_port import LlmCredentialPort, LlmCredentialStatusV1


@dataclass(frozen=True, slots=True)
class GetLlmCredentialStatusQuery:
    provider: str


class GetLlmCredentialStatusHandler:
    def __init__(self, credentials: LlmCredentialPort) -> None:
        self._credentials = credentials

    def __call__(self, query: GetLlmCredentialStatusQuery) -> LlmCredentialStatusV1:
        return self._credentials.get_credential_status(query.provider)


__all__ = ["GetLlmCredentialStatusHandler", "GetLlmCredentialStatusQuery", "LlmCredentialStatusV1"]
