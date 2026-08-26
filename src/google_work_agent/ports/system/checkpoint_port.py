"""Abstract same-Run checkpoint availability and persistence boundary."""

from typing import Protocol

from google_work_agent.ports.system.contracts.checkpoint import GraphCheckpointEnvelopeV1
from google_work_agent.ports.system.contracts.retrieval_head import RetrievalHeadV1
from google_work_agent.ports.system.contracts.workflow_binding import WorkflowBindingV1
from google_work_agent.ports.system.contracts.workflow_handoff import WorkflowControlEnvelopeV1


class CheckpointPort(Protocol):
    def create_workflow_binding(self, binding: WorkflowBindingV1) -> None: ...

    def load_workflow_binding(self, run_id: str) -> WorkflowBindingV1 | None: ...

    def store_same_run_checkpoint(self, checkpoint: GraphCheckpointEnvelopeV1) -> None: ...

    def load_same_run_checkpoint(
        self, run_id: str, thread_id: str
    ) -> GraphCheckpointEnvelopeV1 | None: ...

    def materialize_workflow_control(
        self,
        checkpoint: GraphCheckpointEnvelopeV1,
        control: WorkflowControlEnvelopeV1,
        *,
        goto_node: str | None = None,
    ) -> None: ...

    def contains_workflow_control(
        self,
        checkpoint: GraphCheckpointEnvelopeV1,
        control: WorkflowControlEnvelopeV1,
        *,
        goto_node: str | None = None,
    ) -> bool: ...

    def materialize_resume_target(
        self, checkpoint: GraphCheckpointEnvelopeV1, *, goto_node: str
    ) -> None: ...

    def store_retrieval_head(self, head: RetrievalHeadV1) -> None: ...

    def load_retrieval_head(self, run_id: str) -> RetrievalHeadV1 | None: ...

    def flush(self) -> None: ...

    def delete_run_checkpoints(self, run_id: str) -> None: ...
