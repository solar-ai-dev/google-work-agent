"""Abstract same-Run checkpoint availability and persistence boundary."""

from typing import Protocol

from google_work_agent.ports.system.contracts.checkpoint import GraphCheckpointEnvelopeV1
from google_work_agent.ports.system.contracts.external_llm_transfer_scope import (
    ExternalLlmTransferScopeV1,
)
from google_work_agent.ports.system.contracts.retrieval_head import RetrievalHeadV1
from google_work_agent.ports.system.contracts.workflow_binding import WorkflowBindingV1


class InitialWorkflowBindingPort(Protocol):
    """The sole checkpoint write allowed to participate in StartRun's Domain UoW."""

    def create_workflow_binding(self, binding: WorkflowBindingV1) -> None: ...


class CheckpointPort(Protocol):
    def create_workflow_binding(self, binding: WorkflowBindingV1) -> None: ...

    def load_workflow_binding(self, run_id: str) -> WorkflowBindingV1 | None: ...

    def store_same_run_checkpoint(self, checkpoint: GraphCheckpointEnvelopeV1) -> None: ...

    def load_same_run_checkpoint(
        self, run_id: str, thread_id: str
    ) -> GraphCheckpointEnvelopeV1 | None: ...

    def store_retrieval_head(self, head: RetrievalHeadV1) -> None: ...

    def load_retrieval_head(self, run_id: str) -> RetrievalHeadV1 | None: ...

    def store_external_llm_scope(self, scope: ExternalLlmTransferScopeV1) -> None: ...

    def load_external_llm_scope(self, run_id: str) -> ExternalLlmTransferScopeV1 | None: ...

    def flush(self) -> None: ...

    def delete_run_checkpoints(self, run_id: str) -> None: ...
