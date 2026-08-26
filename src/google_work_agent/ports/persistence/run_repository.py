"""Run persistence port.

STR-149's canonical required callable surface is `create`, `get`,
`get_snapshot`, `find_open_by_conversation`, and
`update_if_version_and_status`. `run.start_run` (CAP-APP-005) uses only
that surface.

Every other method below is a pre-existing, still-actively-called
domain-transition shim (`start_analysis`, `begin_retrieval`, ... `resume_after_reauth`,
`set_recovery_required`, `set_reauth_required`, `set_verifying`) owned by Run
lifecycle capabilities outside #72's bounded scope (CAP-APP-016..022 and
related). Renaming/collapsing them onto the generic canonical surface is a
repository-wide capability cut-over of its own and is intentionally deferred;
see the SQLite adapter for exact remaining callers per method. Per migration
policy they are kept as thin shims whose actual row write now delegates to
`update_if_version_and_status` rather than owning independent SQL.

`get_by_id` still has real callers across the codebase and is kept for the
same reason. `add`/`get_open_by_conversation` had zero remaining callers
(repository-wide search, #72 final cleanup) and were removed outright rather
than kept as dead shims; `create`/`find_open_by_conversation` are the sole
authority for that surface now.
"""

from typing import Protocol

from google_work_agent.domain import CommandResult, RunCommand, RunStatus
from google_work_agent.ports.models import RunCreateRecord, RunRecord


class RunAlreadyOpenConflictError(RuntimeError):
    """A concurrent Run create lost the one-open-Run conversation fence."""


class RunRepository(Protocol):
    # --- STR-149 canonical surface (run.start_run / CAP-APP-005) ---
    def create(self, run: RunCreateRecord) -> None: ...
    def get(self, run_id: str) -> RunRecord | None: ...
    def get_snapshot(self, run_id: str) -> RunRecord | None: ...
    def find_open_by_conversation(self, conversation_id: str) -> RunRecord | None: ...
    def get_latest_by_conversation(self, conversation_id: str) -> RunRecord | None: ...
    def list_by_conversation_bounded(
        self, conversation_id: str, *, limit: int
    ) -> tuple[RunRecord, ...]: ...
    def update_if_version_and_status(
        self,
        run_id: str,
        expected_version: int,
        expected_statuses: frozenset[RunStatus],
        values: dict[str, object],
    ) -> bool: ...

    # --- pre-existing shims kept for lifecycle capabilities outside #73 ---
    def get_by_id(self, run_id: str) -> RunRecord | None: ...
    def resume_after_reauth(
        self,
        run_id: str,
        *,
        expected_version: int,
        resume_status: RunStatus,
        finished_at_ms: int | None = None,
    ) -> CommandResult[RunStatus, RunCommand]: ...
    def complete_answer_only_run(
        self, run_id: str, *, expected_version: int, finished_at_ms: int
    ) -> CommandResult[RunStatus, RunCommand]: ...
    def complete_write_run(
        self, run_id: str, *, expected_version: int, finished_at_ms: int
    ) -> CommandResult[RunStatus, RunCommand]: ...
    def finalize_action_outcomes(
        self, run_id: str, *, expected_version: int, finished_at_ms: int
    ) -> CommandResult[RunStatus, RunCommand]: ...
    def block_run(
        self, run_id: str, *, expected_version: int, finished_at_ms: int
    ) -> CommandResult[RunStatus, RunCommand]: ...
    def fail_run(
        self, run_id: str, *, expected_version: int, finished_at_ms: int
    ) -> CommandResult[RunStatus, RunCommand]: ...
    def publish_read_only_plan(
        self, run_id: str, *, expected_version: int, finished_at_ms: int | None = None
    ) -> CommandResult[RunStatus, RunCommand]: ...
    def complete_read_only_run(
        self, run_id: str, *, expected_version: int, finished_at_ms: int
    ) -> CommandResult[RunStatus, RunCommand]: ...
    def publish_write_plan(
        self, run_id: str, *, expected_version: int, finished_at_ms: int | None = None
    ) -> CommandResult[RunStatus, RunCommand]: ...
    def request_cancel(
        self, run_id: str, *, expected_version: int
    ) -> CommandResult[RunStatus, RunCommand]: ...
    def finalize_cancel(
        self, run_id: str, *, expected_version: int, finished_at_ms: int
    ) -> CommandResult[RunStatus, RunCommand]: ...
    def require_reauth(
        self, run_id: str, *, expected_version: int, finished_at_ms: int | None = None
    ) -> CommandResult[RunStatus, RunCommand]: ...
    def require_recovery(
        self, run_id: str, *, expected_version: int, finished_at_ms: int | None = None
    ) -> CommandResult[RunStatus, RunCommand]: ...
    def resolve_recovery(
        self,
        run_id: str,
        *,
        expected_version: int,
        recovery_next_status: RunStatus,
        finished_at_ms: int | None = None,
        validated_recovery_target: bool = False,
    ) -> CommandResult[RunStatus, RunCommand]: ...
    def set_recovery_required(
        self, run_id: str, *, finished_at_ms: int | None = None
    ) -> RunRecord: ...
    def set_reauth_required(
        self, run_id: str, *, finished_at_ms: int | None = None
    ) -> RunRecord: ...
    def set_verifying(self, run_id: str, *, finished_at_ms: int | None = None) -> RunRecord: ...
