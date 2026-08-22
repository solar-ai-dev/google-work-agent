"""SQLite Run repository extension for canonical confirmation resume."""

from google_work_agent.adapters.persistence.repositories import SQLiteRunRepository
from google_work_agent.domain.run.model import RunCommand
from google_work_agent.domain.confirmation import resume_confirmation as transition_resume_confirmation
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.results import CommandResult


class SQLiteConfirmationRunRepository(SQLiteRunRepository):
    """Adds the explicit ResumeConfirmation Domain transition to Run persistence."""

    def resume_confirmation(
        self,
        run_id: str,
        *,
        expected_version: int,
        resume_status: RunStatus,
        finished_at_ms: int | None = None,
    ) -> CommandResult[RunStatus, RunCommand]:
        current = self.get_by_id(run_id)
        if current is None:
            raise LookupError(f"run not found: {run_id}")
        result = transition_resume_confirmation(
            current.status,
            current_version=current.version,
            expected_version=expected_version,
            resume_status=resume_status,
        )
        if not result.applied:
            return result
        self._apply_run_transition(
            run_id=run_id,
            previous_version=current.version,
            status=result.current_status,
            version=result.current_version,
            finished_at_ms=finished_at_ms,
            error_message="run resume-confirmation affected an unexpected row count",
        )
        return result
