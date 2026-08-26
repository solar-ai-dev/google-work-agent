"""Plan repository compatibility for reserved corrective-plan drafts."""

from __future__ import annotations

import sqlite3

from google_work_agent.adapters.persistence.sqlite.repositories.plan_repository import (
    SQLitePlanRepository,
)
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanStatus


class CorrectiveAwareSQLitePlanRepository(SQLitePlanRepository):
    """Allow Planning to populate the server-reserved corrective DRAFT row.

    ResolveRecovery(CREATE_CORRECTIVE_PLAN) reserves the next revision before
    workflow continuation. The legacy SaveWritePlan boundary still calls
    ``insert_draft`` when Planning materializes actions. Reusing the exact
    server-generated DRAFT id is safe only while that row is still empty,
    DRAFT, and has the exact reserved revision number; every other duplicate
    remains fail-closed.
    """

    def insert_draft(self, plan: PlanRecord) -> None:
        existing = self.get_by_id(plan.id)
        if existing is None:
            super().insert_draft(plan)
            return
        if (
            existing.run_id != plan.run_id
            or existing.revision_no != plan.revision_no
            or existing.status is not PlanStatus.DRAFT
            or self._connection.execute(
                "SELECT 1 FROM actions WHERE plan_id = ? LIMIT 1;",
                (plan.id,),
            ).fetchone()
            is not None
        ):
            raise sqlite3.IntegrityError(
                "existing plan is not the exact empty reserved corrective draft"
            )
        self._connection.execute(
            "UPDATE plans SET summary_text = ? WHERE id = ? AND status = 'DRAFT';",
            (plan.summary_text, plan.id),
        )


__all__ = ["CorrectiveAwareSQLitePlanRepository"]
