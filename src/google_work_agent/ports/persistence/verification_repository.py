"""Verification persistence port."""

from typing import Protocol

from google_work_agent.domain.verification.model import Verification as VerificationRecord


class VerificationRepository(Protocol):
    def insert(self, record: VerificationRecord) -> None: ...
    def list_by_attempt(self, execution_attempt_id: str) -> tuple[VerificationRecord, ...]: ...
