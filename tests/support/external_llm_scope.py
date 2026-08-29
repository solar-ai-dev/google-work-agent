"""Test support for the external-LLM disclosure checkpoint gate."""

from dataclasses import dataclass

from google_work_agent.application.use_cases.run.project_external_llm_transfer_scope import (
    ProjectExternalLlmTransferScopeHandler,
)
from google_work_agent.ports.system.contracts.external_llm_transfer_scope import (
    ExternalLlmTransferScopeV1,
)


@dataclass
class ExternalScopeCheckpoint:
    scope: ExternalLlmTransferScopeV1 | None = None
    flush_count: int = 0

    def load_external_llm_scope(self, run_id: str) -> ExternalLlmTransferScopeV1 | None:
        return self.scope if self.scope is not None and self.scope.run_id == run_id else None

    def store_external_llm_scope(self, scope: ExternalLlmTransferScopeV1) -> None:
        self.scope = scope

    def flush(self) -> None:
        self.flush_count += 1


def build_external_scope_gate() -> tuple[
    ExternalScopeCheckpoint, ProjectExternalLlmTransferScopeHandler
]:
    checkpoint = ExternalScopeCheckpoint()
    return checkpoint, ProjectExternalLlmTransferScopeHandler(checkpoint)  # type: ignore[arg-type]


__all__ = ["ExternalScopeCheckpoint", "build_external_scope_gate"]
