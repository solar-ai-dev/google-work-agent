"""Run persistence/query/CAS port."""

from typing import Protocol

from google_work_agent.domain.run.model import Run, RunCreate, RunStatus


class RunAlreadyOpenConflictError(RuntimeError):
    """A concurrent Run create lost the one-open-Run conversation fence."""


class RunRepository(Protocol):
    def create(self, run: RunCreate) -> None: ...
    def get(self, run_id: str) -> Run | None: ...
    def get_snapshot(self, run_id: str) -> Run | None: ...
    def find_open_by_conversation(self, conversation_id: str) -> Run | None: ...
    def get_latest_by_conversation(self, conversation_id: str) -> Run | None: ...
    def list_by_conversation_bounded(
        self, conversation_id: str, *, limit: int
    ) -> tuple[Run, ...]: ...
    def update_if_version_and_status(
        self,
        run_id: str,
        expected_version: int,
        expected_statuses: frozenset[RunStatus],
        values: dict[str, object],
    ) -> bool: ...
