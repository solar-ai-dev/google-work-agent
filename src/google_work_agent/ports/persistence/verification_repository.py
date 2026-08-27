"""Verification persistence port."""

from typing import Protocol

from google_work_agent.domain.verification.model import Verification as VerificationRecord


class VerificationRepository(Protocol):
    def insert(self, record: VerificationRecord) -> None: ...
    def get_latest_for_attempt(self, execution_attempt_id: str) -> VerificationRecord | None: ...
    def list_for_action(self, action_id: str) -> tuple[VerificationRecord, ...]: ...
