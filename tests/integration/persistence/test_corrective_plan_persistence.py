"""Functional SQLite regression for reserved corrective-plan persistence."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

from google_work_agent.adapters.langgraph.canonical_freshness_runtime import (
    LangGraphWorkflowRuntime,
)
from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.connector_identity import bind_action_connector_ids
from google_work_agent.adapters.persistence.unit_of_work import (
    SQLiteUnitOfWork,
    sqlite_unit_of_work_factory,
)
from google_work_agent.application.write_actions import (
    PublishWritePlanService,
    RecoveryResolutionKind,
    ResolveMismatchRecoveryCommand,
    ResolveMismatchRecoveryService,
    SaveWritePlanService,
)
from google_work_agent.application.workflows.retrieval_evidence_store import RunScopedEvidenceStore
from google_work_agent.domain import calculate_canonical_json_hash
from google_work_agent.ports import ActionRecord, EvidenceOriginType, EvidenceRecord, PlanRecord


def _seed_recovery_aggregate(database_path: Path) -> None:
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('account-1', 'u@example.com', NULL, 1, NULL);"
        )
        connection.execute(
            "INSERT INTO conversations VALUES ('conversation-1', 'account-1', 'Test', 1, 1);"
        )
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'RECOVERY_REQUIRED',
                      'thread-1', 'AUTO', '{}', 5, 1);
            """
        )
        connection.execute(
            """
            INSERT INTO plans (
                id, run_id, revision_no, status, summary_text, created_at_ms,
                review_status, review_version
            ) VALUES ('old-plan', 'run-1', 1, 'ACTIVE', 'old', 2, 'PASSED', 0);
            """
        )
        connection.commit()
    finally:
        connection.close()

    old_actions = (
        ActionRecord(
            id="old-action-1",
            plan_id="old-plan",
            position=1,
            tool_name="gmail_send",
            effect_type="SEND",
            approval_requirement="REQUIRED",
            verification_policy="SENT_LOOKUP",
            recovery_policy="MESSAGE_SEARCH",
            target_resource_ref_id=None,
            status="MISMATCH",
            arguments_json='{"draft_id":"draft-old-1"}',
            arguments_hash="a" * 64,
            expected_json='{"resource_type":"gmail_message"}',
            risk={},
            version=3,
            created_at_ms=3,
            updated_at_ms=4,
        ),
        ActionRecord(
            id="old-action-2",
            plan_id="old-plan",
            position=2,
            tool_name="gmail_send",
            effect_type="SEND",
            approval_requirement="REQUIRED",
            verification_policy="SENT_LOOKUP",
            recovery_policy="MESSAGE_SEARCH",
            target_resource_ref_id=None,
            status="DEPENDENCY_BLOCKED",
            arguments_json='{"draft_id":"draft-old-2"}',
            arguments_hash="b" * 64,
            expected_json='{"resource_type":"gmail_message"}',
            risk={},
            version=1,
            created_at_ms=3,
            updated_at_ms=4,
        ),
    )
    old_evidence = (
        EvidenceRecord(
            id="old-evidence-1",
            run_id="run-1",
            origin_type=EvidenceOriginType.DERIVED,
            resource_ref_id=None,
            message_id=None,
            kind="FACT",
            excerpt="old evidence one",
            locator_json=None,
            created_at_ms=3,
        ),
        EvidenceRecord(
            id="old-evidence-2",
            run_id="run-1",
            origin_type=EvidenceOriginType.DERIVED,
            resource_ref_id=None,
            message_id=None,
            kind="FACT",
            excerpt="old evidence two",
            locator_json=None,
            created_at_ms=3,
        ),
    )
    with (
        bind_action_connector_ids(
            {"old-action-1": "google_workspace", "old-action-2": "google_workspace"}
        ),
        SQLiteUnitOfWork(database_path) as unit_of_work,
    ):
        for evidence in old_evidence:
            unit_of_work.evidence.insert(evidence)
        for action in old_actions:
            unit_of_work.actions.insert_write_action(action)
        unit_of_work.action_dependencies.add(
            action_id="old-action-2",
            depends_on_action_id="old-action-1",
        )
        unit_of_work.evidence.link_to_action(
            action_id="old-action-1", evidence_id="old-evidence-1"
        )
        unit_of_work.evidence.link_to_action(
            action_id="old-action-2", evidence_id="old-evidence-2"
        )
        unit_of_work.commit()


class _CorrectivePersistenceHarness:
    def __init__(self, database_path: Path) -> None:
        self._unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
        self._now_ms = lambda: 10
        self._save_write_plan = SaveWritePlanService(
            unit_of_work_factory=self._unit_of_work_factory,
            now_ms=self._now_ms,
        )
        self._publish_write_plan = PublishWritePlanService(
            unit_of_work_factory=self._unit_of_work_factory,
            now_ms=self._now_ms,
        )
        self._evidence_store = RunScopedEvidenceStore()
        identifiers: Iterator[str] = iter(
            (
                "new-action-1",
                "new-action-2",
                "new-evidence-1",
                "new-evidence-2",
                "save-corrective-command",
                "publish-corrective-command",
            )
        )
        self._id_factory = lambda: next(identifiers)

    def _current_run_version(self, run_id: str) -> int:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get_by_id(run_id)
            assert run is not None
            return run.version

    def _plans_for_run(self, run_id: str) -> tuple[PlanRecord, ...]:
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.plans.list_by_run(run_id)

    @staticmethod
    def _resolve_target_resource_ref_id(**_: Any) -> None:
        return None

    @staticmethod
    def _calendar_plan_risk(**_: Any) -> dict[str, object]:
        return {}

    @staticmethod
    def _request_hash(payload: dict[str, object]) -> str:
        return calculate_canonical_json_hash(payload)

    @staticmethod
    def _required_string(value: object, field_name: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{field_name} is required")
        return value


def test_reserved_corrective_plan_preserves_plan_identity_and_remaps_children(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "corrective-persistence.db"
    _seed_recovery_aggregate(database_path)
    factory = sqlite_unit_of_work_factory(database_path)

    resolution = ResolveMismatchRecoveryService(
        unit_of_work_factory=factory,
        now_ms=lambda: 6,
    )(
        ResolveMismatchRecoveryCommand(
            command_id="resolve-corrective-1",
            request_hash="c" * 64,
            run_id="run-1",
            action_id="old-action-1",
            expected_run_version=5,
            resolution_kind=RecoveryResolutionKind.CREATE_CORRECTIVE_PLAN,
            corrective_plan_id="reserved-plan-2",
        )
    )
    assert resolution.applied is True
    assert resolution.run_status == "PLANNING"
    assert resolution.plan_id == "reserved-plan-2"
    assert resolution.plan_status == "DRAFT"

    harness = _CorrectivePersistenceHarness(database_path)
    harness._evidence_store.put(
        run_id="run-1",
        evidence_drafts=[
            {
                "schema_version": 1,
                "evidence_id": "old-evidence-1",
                "resource_handle": "resource-1",
                "segment_id": "segment-1",
                "kind": "FACT",
                "excerpt": "corrective evidence one",
                "locator": None,
                "reason_codes": [],
            },
            {
                "schema_version": 1,
                "evidence_id": "old-evidence-2",
                "resource_handle": "resource-2",
                "segment_id": "segment-2",
                "kind": "FACT",
                "excerpt": "corrective evidence two",
                "locator": None,
                "reason_codes": [],
            },
        ],
    )
    state = cast(
        dict[str, Any],
        {
            "run_id": "run-1",
            "__reserved_corrective_plan_id__": "reserved-plan-2",
            "__replan_from_plan_id__": None,
            "tool_route_plan": {
                "output_plan": {
                    "output_mode": "ACTION",
                    "output_routes": [
                        {
                            "selected_tool_id": "gmail_send",
                            "effect": "SEND",
                            "connector_id": "google_workspace",
                        },
                        {
                            "selected_tool_id": "gmail_send",
                            "effect": "SEND",
                            "connector_id": "google_workspace",
                        },
                    ],
                }
            },
            "retrieval_result": {
                "evidence_refs": ["old-evidence-1", "old-evidence-2"],
            },
            "acquisition_result": {},
        },
    )
    corrective_draft = cast(
        dict[str, Any],
        {
            "schema_version": 2,
            "status": "PLAN_READY",
            "plan_id": "logical-candidate-plan",
            "summary": "corrective send sequence",
            "objective": "repair mismatch",
            "actions": [
                {
                    "schema_version": 2,
                    "action_id": "old-action-1",
                    "position": 1,
                    "effect": "SEND",
                    "tool_name": "gmail_send",
                    "arguments": {"draft_id": "draft-new-1"},
                    "expected": {"llm_owned": "must be replaced"},
                    "evidence_refs": ["old-evidence-1"],
                    "resource_refs": [],
                    "target_resource_ref_id": None,
                    "depends_on_action_ids": [],
                    "user_visible_reason": "send corrected message one",
                },
                {
                    "schema_version": 2,
                    "action_id": "old-action-2",
                    "position": 2,
                    "effect": "SEND",
                    "tool_name": "gmail_send",
                    "arguments": {"draft_id": "draft-new-2"},
                    "expected": {"llm_owned": "must be replaced"},
                    "evidence_refs": ["old-evidence-2"],
                    "resource_refs": [],
                    "target_resource_ref_id": None,
                    "depends_on_action_ids": ["old-action-1"],
                    "user_visible_reason": "send corrected message two",
                },
            ],
            "evidence_refs": ["old-evidence-1", "old-evidence-2"],
            "resource_refs": [],
            "confirmation": None,
        },
    )

    persisted_plan_id = LangGraphWorkflowRuntime._persist_write_plan(
        cast(Any, harness),
        cast(Any, state),
        cast(Any, corrective_draft),
    )
    assert persisted_plan_id == "reserved-plan-2"
    assert state["__reserved_corrective_plan_id__"] is None

    connection = connect_sqlite(database_path)
    try:
        plans = connection.execute(
            "SELECT id, revision_no, status FROM plans WHERE run_id = 'run-1' ORDER BY revision_no;"
        ).fetchall()
        assert [tuple(row) for row in plans] == [
            ("old-plan", 1, "SUPERSEDED"),
            ("reserved-plan-2", 2, "WAITING_APPROVAL"),
        ]
        assert connection.execute(
            "SELECT COUNT(*) FROM plans WHERE run_id = 'run-1' AND revision_no > 2;"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT status FROM runs WHERE id = 'run-1';"
        ).fetchone()[0] == "WAITING_APPROVAL"

        new_actions = connection.execute(
            "SELECT id, connector_id FROM actions WHERE plan_id = 'reserved-plan-2' ORDER BY position;"
        ).fetchall()
        assert [tuple(row) for row in new_actions] == [
            ("new-action-1", "google_workspace"),
            ("new-action-2", "google_workspace"),
        ]
        assert {row[0] for row in new_actions}.isdisjoint({"old-action-1", "old-action-2"})

        new_links = connection.execute(
            """
            SELECT ae.action_id, ae.evidence_id
            FROM action_evidence AS ae
            JOIN actions AS a ON a.id = ae.action_id
            WHERE a.plan_id = 'reserved-plan-2'
            ORDER BY ae.action_id, ae.evidence_id;
            """
        ).fetchall()
        assert [tuple(row) for row in new_links] == [
            ("new-action-1", "new-evidence-1"),
            ("new-action-2", "new-evidence-2"),
        ]
        assert {row[1] for row in new_links}.isdisjoint(
            {"old-evidence-1", "old-evidence-2"}
        )

        dependencies = connection.execute(
            """
            SELECT action_id, depends_on_action_id
            FROM action_dependencies
            WHERE action_id IN ('new-action-1', 'new-action-2')
            ORDER BY action_id, depends_on_action_id;
            """
        ).fetchall()
        assert [tuple(row) for row in dependencies] == [
            ("new-action-2", "new-action-1"),
        ]
        assert connection.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        connection.close()
