"""SQLite plan repository including corrective-plan draft reuse."""

import sqlite3

from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import (
    ActionDependency,
    ActionEvidence,
    parse_action_risk_json,
)
from google_work_agent.domain.evidence.model import Evidence, EvidenceOriginType
from google_work_agent.domain.plan.model import (
    PLAN_REVIEW_DISPOSITIONS,
    PlanReviewStatus,
    PlanStatusV1,
)
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.ports.persistence.plan_repository import PlanBundle


class SqlitePlanRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @staticmethod
    def _record(row: sqlite3.Row) -> PlanRecord:
        return PlanRecord(
            id=str(row["id"]),
            run_id=str(row["run_id"]),
            revision_no=int(row["revision_no"]),
            status=PlanStatusV1(str(row["status"])),
            summary_text=None if row["summary_text"] is None else str(row["summary_text"]),
            created_at_ms=int(row["created_at_ms"]),
            review_status=PlanReviewStatus(str(row["review_status"])),
            review_version=int(row["review_version"]),
            review_disposition=(
                None if row["review_disposition"] is None else str(row["review_disposition"])
            ),
        )

    def _get_plan(self, plan_id: str) -> PlanRecord | None:
        row = self._connection.execute(
            """SELECT id, run_id, revision_no, status, summary_text, created_at_ms,
                      review_status, review_version, review_disposition
               FROM plans WHERE id = ?;""",
            (plan_id,),
        ).fetchone()
        return None if row is None else self._record(row)

    def load_bundle(self, plan_id: str) -> PlanBundle | None:
        plan = self._get_plan(plan_id)
        if plan is None:
            return None
        action_rows = self._connection.execute(
            """SELECT id, plan_id, connector_id, position, tool_name, effect_type,
                      approval_requirement, verification_policy, recovery_policy,
                      target_resource_ref_id, status, arguments_json, arguments_hash,
                      expected_json, risk_json, version, created_at_ms, updated_at_ms
               FROM actions WHERE plan_id=? ORDER BY position, id;""",
            (plan_id,),
        ).fetchall()
        dependency_rows = self._connection.execute(
            """SELECT d.action_id, d.depends_on_action_id
               FROM action_dependencies AS d
               JOIN actions AS a ON a.id=d.action_id
               WHERE a.plan_id=? ORDER BY d.action_id, d.depends_on_action_id;""",
            (plan_id,),
        ).fetchall()
        evidence_rows = self._connection.execute(
            """SELECT ae.action_id, e.id, e.run_id, e.origin_type,
                      e.resource_ref_id, e.message_id, e.kind, e.excerpt,
                      e.locator_json, e.created_at_ms
               FROM action_evidence AS ae
               JOIN actions AS a ON a.id=ae.action_id
               JOIN evidence AS e ON e.id=ae.evidence_id
               WHERE a.plan_id=?
               ORDER BY e.created_at_ms, e.id, ae.action_id;""",
            (plan_id,),
        ).fetchall()
        evidence_by_id: dict[str, Evidence] = {}
        action_evidence: list[ActionEvidence] = []
        for row in evidence_rows:
            evidence_id = str(row["id"])
            evidence_by_id.setdefault(evidence_id, self._evidence_record(row))
            action_evidence.append(
                ActionEvidence(action_id=str(row["action_id"]), evidence_id=evidence_id)
            )
        return PlanBundle(
            plan=plan,
            actions=tuple(self._action_record(row) for row in action_rows),
            dependencies=tuple(
                ActionDependency(
                    action_id=str(row["action_id"]),
                    depends_on_action_id=str(row["depends_on_action_id"]),
                )
                for row in dependency_rows
            ),
            evidence=tuple(evidence_by_id.values()),
            action_evidence=tuple(action_evidence),
        )

    def get_current(self, run_id: str) -> PlanRecord | None:
        row = self._connection.execute(
            """SELECT id, run_id, revision_no, status, summary_text, created_at_ms,
                      review_status, review_version, review_disposition
               FROM plans WHERE run_id=? ORDER BY revision_no DESC LIMIT 1;""",
            (run_id,),
        ).fetchone()
        return None if row is None else self._record(row)

    def insert_revision(self, plan: PlanRecord) -> None:
        existing = self._get_plan(plan.id)
        if existing is None:
            self._connection.execute(
                """INSERT INTO plans (
                       id, run_id, revision_no, status, summary_text, created_at_ms,
                       review_status, review_version, review_disposition
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                (
                    plan.id,
                    plan.run_id,
                    plan.revision_no,
                    plan.status.value,
                    plan.summary_text,
                    plan.created_at_ms,
                    plan.review_status.value,
                    plan.review_version,
                    plan.review_disposition,
                ),
            )
            return
        has_actions = (
            self._connection.execute(
                "SELECT 1 FROM actions WHERE plan_id = ? LIMIT 1;", (plan.id,)
            ).fetchone()
            is not None
        )
        if (
            existing.run_id != plan.run_id
            or existing.revision_no != plan.revision_no
            or existing.status is not PlanStatusV1.DRAFT
            or has_actions
        ):
            raise sqlite3.IntegrityError(
                "existing plan is not the exact empty reserved corrective draft"
            )
        self._connection.execute(
            """UPDATE plans
               SET summary_text=?, review_status=?, review_version=?, review_disposition=?
               WHERE id=? AND status='DRAFT';""",
            (
                plan.summary_text,
                plan.review_status.value,
                plan.review_version,
                plan.review_disposition,
                plan.id,
            ),
        )

    def update_if_version_and_status(
        self,
        plan_id: str,
        expected_version: int,
        expected_statuses: frozenset[PlanStatusV1],
        values: dict[str, object],
    ) -> bool:
        if not values or not expected_statuses:
            raise ValueError("Plan CAS requires values and expected statuses")
        if not set(values).issubset({"status"}):
            raise ValueError("Plan CAS contains an unsupported column")
        normalized = {
            key: value.value if isinstance(value, PlanStatusV1) else value
            for key, value in values.items()
        }
        set_clause = ", ".join(f"{column}=?" for column in normalized)
        placeholders = ", ".join("?" for _ in expected_statuses)
        cursor = self._connection.execute(
            f"UPDATE plans SET {set_clause} WHERE id=? AND revision_no=? "
            f"AND status IN ({placeholders});",
            [
                *normalized.values(),
                plan_id,
                expected_version,
                *(status.value for status in expected_statuses),
            ],
        )
        return cursor.rowcount == 1

    def record_review_result(
        self,
        plan_id: str,
        *,
        expected_review_version: int,
        expected_review_statuses: frozenset[PlanReviewStatus],
        values: dict[str, object],
    ) -> PlanRecord | None:
        if not values or not expected_review_statuses:
            raise ValueError("Plan review CAS requires values and expected statuses")
        allowed_columns = {"review_status", "review_version", "review_disposition"}
        if not set(values).issubset(allowed_columns):
            raise ValueError("Plan review CAS contains an unsupported column")
        if "review_status" not in values or "review_disposition" not in values:
            raise ValueError("Plan review CAS requires one coherent gate/disposition snapshot")
        status = values["review_status"]
        status_value = status.value if isinstance(status, PlanReviewStatus) else str(status)
        disposition = values["review_disposition"]
        if disposition is not None and disposition not in PLAN_REVIEW_DISPOSITIONS:
            raise ValueError("Plan review disposition is outside the canonical closed set")
        if (status_value == "PASSED") != (disposition == "PASS"):
            raise ValueError("Plan review gate/disposition snapshot is impossible")
        normalized = {
            key: value.value if isinstance(value, PlanReviewStatus) else value
            for key, value in values.items()
        }
        set_clause = ", ".join(f"{column}=?" for column in normalized)
        placeholders = ", ".join("?" for _ in expected_review_statuses)
        cursor = self._connection.execute(
            f"UPDATE plans SET {set_clause} WHERE id=? AND review_version=? "
            f"AND review_status IN ({placeholders});",
            [
                *normalized.values(),
                plan_id,
                expected_review_version,
                *(status.value for status in expected_review_statuses),
            ],
        )
        return None if cursor.rowcount != 1 else self._get_plan(plan_id)

    @staticmethod
    def _action_record(row: sqlite3.Row) -> ActionRecord:
        return ActionRecord(
            id=str(row["id"]),
            plan_id=str(row["plan_id"]),
            connector_id=str(row["connector_id"]),
            position=int(row["position"]),
            tool_name=str(row["tool_name"]),
            effect_type=str(row["effect_type"]),
            approval_requirement=str(row["approval_requirement"]),
            verification_policy=str(row["verification_policy"]),
            recovery_policy=str(row["recovery_policy"]),
            target_resource_ref_id=(
                None
                if row["target_resource_ref_id"] is None
                else str(row["target_resource_ref_id"])
            ),
            status=str(row["status"]),
            arguments_json=str(row["arguments_json"]),
            arguments_hash=str(row["arguments_hash"]),
            expected_json=str(row["expected_json"]),
            risk=parse_action_risk_json(str(row["risk_json"])),
            version=int(row["version"]),
            created_at_ms=int(row["created_at_ms"]),
            updated_at_ms=int(row["updated_at_ms"]),
        )

    @staticmethod
    def _evidence_record(row: sqlite3.Row) -> Evidence:
        return Evidence(
            id=str(row["id"]),
            run_id=str(row["run_id"]),
            origin_type=EvidenceOriginType(str(row["origin_type"])),
            resource_ref_id=(
                None if row["resource_ref_id"] is None else str(row["resource_ref_id"])
            ),
            message_id=None if row["message_id"] is None else str(row["message_id"]),
            kind=str(row["kind"]),
            excerpt=str(row["excerpt"]),
            locator_json=None if row["locator_json"] is None else str(row["locator_json"]),
            created_at_ms=int(row["created_at_ms"]),
        )
