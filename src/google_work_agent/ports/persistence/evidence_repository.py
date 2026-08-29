"""Evidence persistence port."""

from typing import Protocol

from google_work_agent.domain.evidence.model import Evidence as EvidenceRecord


class EvidenceRepository(Protocol):
    def insert_bounded(
        self, record: EvidenceRecord, *, action_ids: tuple[str, ...] = ()
    ) -> None: ...
    def list_for_run(self, run_id: str, *, limit: int = 500) -> tuple[EvidenceRecord, ...]: ...
    def list_for_retrieval_artifact(
        self, run_id: str, retrieval_artifact_id: str, *, limit: int = 100
    ) -> tuple[EvidenceRecord, ...]: ...
    def list_for_action(self, action_id: str) -> tuple[EvidenceRecord, ...]: ...
