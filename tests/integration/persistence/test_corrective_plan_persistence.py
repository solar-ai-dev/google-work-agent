"""Functional SQLite regressions for reserved corrective-plan persistence."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.main.state import ParentGraphState
from google_work_agent.adapters.langgraph.main.workflow import (
    LangGraphWorkflowRuntime,
)
from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import (
    SqliteUnitOfWork,
    sqlite_unit_of_work_factory,
)
from google_work_agent.adapters.system.memory.retrieval_evidence_store import (
    RunScopedEvidenceStore,
)
from google_work_agent.application.use_cases.plan.persistence_projection import current_plan_tuple
from google_work_agent.application.use_cases.plan.record_review_result import (
    RecordReviewResultHandler,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.evidence.model import Evidence as EvidenceRecord
from google_work_agent.domain.evidence.model import EvidenceOriginType
from google_work_agent.domain.plan.model import Plan as PlanRecord
from tests.support.checkpoint import sqlite_checkpoint
from tests.support.legacy_write.write_actions import PublishPlanHandler
from tests.support.resolve_recovery_adapter import (
    RecoveryResolutionKind,
    ResolveMismatchRecoveryCommand,
    ResolveMismatchRecoveryService,
)


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
                review_status, review_version, review_disposition
            ) VALUES (
                'old-plan', 'run-1', 1, 'ACTIVE', 'old', 2, 'PASSED', 0, 'PASS'
            );
            """
        )
        connection.commit()
    finally:
        connection.close()

    old_actions = (
        ActionRecord(
            id="old-action-1",
            plan_id="old-plan",
            connector_id="google_workspace",
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
            connector_id="google_workspace",
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
    with SqliteUnitOfWork(database_path) as unit_of_work:
        for evidence in old_evidence:
            unit_of_work.evidence.insert_bounded(evidence)
        unit_of_work.actions.insert_for_plan(
            old_actions[0],
            evidence_ids=("old-evidence-1",),
        )
        unit_of_work.actions.insert_for_plan(
            old_actions[1],
            dependency_ids=("old-action-1",),
            evidence_ids=("old-evidence-2",),
        )
        unit_of_work.commit()


class _CorrectivePersistenceHarness:
    def __init__(self, database_path: Path, *, fail_publish_once: bool = False) -> None:
        self._unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
        self._now_ms = lambda: 10
        self._save_delegate = PublishPlanHandler(
            unit_of_work_factory=self._unit_of_work_factory,
            now_ms=self._now_ms,
        )
        self._publish_delegate = PublishPlanHandler(
            unit_of_work_factory=self._unit_of_work_factory,
            now_ms=self._now_ms,
        )
        self._record_review_result = RecordReviewResultHandler(
            unit_of_work_factory=self._unit_of_work_factory,
            now_ms=self._now_ms,
        )
        self._evidence_store = RunScopedEvidenceStore()
        self.save_calls = 0
        self.publish_calls = 0
        self._fail_publish_once = fail_publish_once

    def _save_write_plan(self, command: Any) -> Any:
        self.save_calls += 1
        return self._save_delegate(command)

    def _publish_write_plan(self, command: Any) -> Any:
        self.publish_calls += 1
        if self._fail_publish_once:
            self._fail_publish_once = False
            raise RuntimeError("injected publish failure before PublishPlanHandler")
        return self._publish_delegate(command)

    @staticmethod
    def _id_factory() -> str:
        raise AssertionError("corrective persistence must not allocate retry-local random ids")

    def _current_run_version(self, run_id: str) -> int:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(run_id)
            assert run is not None
            return run.version

    def _plans_for_run(self, run_id: str) -> tuple[PlanRecord, ...]:
        with self._unit_of_work_factory() as unit_of_work:
            return current_plan_tuple(unit_of_work.plans, run_id)

    @staticmethod
    def _resolve_target_resource_ref_for_connector(**_: Any) -> None:
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


def _resolve_corrective(database_path: Path) -> None:
    result = ResolveMismatchRecoveryService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        checkpoint_port=sqlite_checkpoint(database_path),
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
    assert result.applied is True
    assert result.run_status == "PLANNING"
    assert result.plan_id == "reserved-plan-2"
    assert result.plan_status == "DRAFT"


def _state_and_draft(
    harness: _CorrectivePersistenceHarness,
) -> tuple[dict[str, Any], dict[str, Any]]:
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
            "plan_review": {
                "status": "PASS",
                "meta": {"revision": 1, "artifact_id": "review-corrective-1"},
            },
        },
    )
    draft = cast(
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
    return state, draft


def _prepare(
    database_path: Path,
    *,
    fail_publish_once: bool = False,
) -> tuple[_CorrectivePersistenceHarness, dict[str, Any], dict[str, Any]]:
    _seed_recovery_aggregate(database_path)
    _resolve_corrective(database_path)
    harness = _CorrectivePersistenceHarness(
        database_path,
        fail_publish_once=fail_publish_once,
    )
    state, draft = _state_and_draft(harness)
    return harness, state, draft


def _persist(
    harness: _CorrectivePersistenceHarness,
    state: dict[str, Any],
    draft: dict[str, Any],
) -> str:
    return LangGraphWorkflowRuntime._persist_write_plan(
        cast(Any, harness),
        cast(Any, state),
        cast(Any, draft),
    )


def _aggregate_snapshot(database_path: Path) -> dict[str, Any]:
    connection = connect_sqlite(database_path)
    try:
        plans = [
            tuple(row)
            for row in connection.execute(
                "SELECT id, revision_no, status FROM plans "
                "WHERE run_id = 'run-1' ORDER BY revision_no;"
            ).fetchall()
        ]
        run_status = connection.execute("SELECT status FROM runs WHERE id = 'run-1';").fetchone()[0]
        new_actions = [
            tuple(row)
            for row in connection.execute(
                "SELECT id, connector_id FROM actions "
                "WHERE plan_id = 'reserved-plan-2' ORDER BY position;"
            ).fetchall()
        ]
        new_links = [
            tuple(row)
            for row in connection.execute(
                """
                SELECT ae.action_id, ae.evidence_id
                FROM action_evidence AS ae
                JOIN actions AS a ON a.id = ae.action_id
                WHERE a.plan_id = 'reserved-plan-2'
                ORDER BY ae.action_id, ae.evidence_id;
                """
            ).fetchall()
        ]
        dependencies = [
            tuple(row)
            for row in connection.execute(
                """
                SELECT ad.action_id, ad.depends_on_action_id
                FROM action_dependencies AS ad
                JOIN actions AS a ON a.id = ad.action_id
                WHERE a.plan_id = 'reserved-plan-2'
                ORDER BY ad.action_id, ad.depends_on_action_id;
                """
            ).fetchall()
        ]
        new_evidence_ids = {
            row[0]
            for row in connection.execute(
                """
                SELECT DISTINCT e.id
                FROM evidence AS e
                JOIN action_evidence AS ae ON ae.evidence_id = e.id
                JOIN actions AS a ON a.id = ae.action_id
                WHERE a.plan_id = 'reserved-plan-2';
                """
            ).fetchall()
        }
        command_receipts = [
            tuple(row)
            for row in connection.execute(
                """
                SELECT command_type, status, request_hash
                FROM command_receipts
                WHERE command_type IN ('SaveWritePlan', 'PublishWritePlan')
                ORDER BY command_type, command_id;
                """
            ).fetchall()
        ]
        trace_counts = dict(
            connection.execute(
                """
                SELECT event_type, COUNT(*)
                FROM trace_events
                WHERE run_id = 'run-1'
                  AND event_type IN ('WRITE_PLAN_SAVED', 'PLAN_PUBLISHED')
                GROUP BY event_type;
                """
            ).fetchall()
        )
        rev3_count = connection.execute(
            "SELECT COUNT(*) FROM plans WHERE run_id = 'run-1' AND revision_no > 2;"
        ).fetchone()[0]
        foreign_key_violations = connection.execute("PRAGMA foreign_key_check;").fetchall()
        return {
            "plans": plans,
            "run_status": run_status,
            "new_actions": new_actions,
            "new_links": new_links,
            "dependencies": dependencies,
            "new_evidence_ids": new_evidence_ids,
            "command_receipts": command_receipts,
            "trace_counts": trace_counts,
            "rev3_count": rev3_count,
            "foreign_key_violations": foreign_key_violations,
        }
    finally:
        connection.close()


def _assert_published_snapshot(snapshot: dict[str, Any]) -> None:
    assert snapshot["plans"] == [
        ("old-plan", 1, "SUPERSEDED"),
        ("reserved-plan-2", 2, "WAITING_APPROVAL"),
    ]
    assert snapshot["run_status"] == "WAITING_APPROVAL"
    assert snapshot["rev3_count"] == 0
    assert len(snapshot["new_actions"]) == 2
    action_ids = {row[0] for row in snapshot["new_actions"]}
    assert action_ids.isdisjoint({"old-action-1", "old-action-2"})
    assert {row[1] for row in snapshot["new_actions"]} == {"google_workspace"}
    assert len(snapshot["new_evidence_ids"]) == 2
    assert snapshot["new_evidence_ids"].isdisjoint({"old-evidence-1", "old-evidence-2"})
    assert len(snapshot["new_links"]) == 2
    assert {row[0] for row in snapshot["new_links"]} == action_ids
    assert {row[1] for row in snapshot["new_links"]} == snapshot["new_evidence_ids"]
    assert len(snapshot["dependencies"]) == 1
    child, parent = snapshot["dependencies"][0]
    assert child in action_ids
    assert parent in action_ids
    assert child != parent
    assert snapshot["trace_counts"] == {
        "PLAN_PUBLISHED": 1,
        "WRITE_PLAN_SAVED": 1,
    }
    assert snapshot["foreign_key_violations"] == []


def test_reserved_corrective_plan_preserves_plan_identity_and_remaps_children(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "corrective-persistence.db"
    harness, state, draft = _prepare(database_path)

    assert _persist(harness, state, draft) == "reserved-plan-2"
    assert state["__reserved_corrective_plan_id__"] is None
    assert harness.save_calls == 1
    assert harness.publish_calls == 1

    _assert_published_snapshot(_aggregate_snapshot(database_path))


def test_save_success_publish_failure_retries_with_publish_only(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "corrective-publish-retry.db"
    harness, state, draft = _prepare(database_path, fail_publish_once=True)

    with pytest.raises(RuntimeError, match="injected publish failure"):
        _persist(harness, state, draft)

    after_failure = _aggregate_snapshot(database_path)
    assert after_failure["plans"] == [
        ("old-plan", 1, "SUPERSEDED"),
        ("reserved-plan-2", 2, "DRAFT"),
    ]
    assert after_failure["run_status"] == "PLANNING"
    assert after_failure["rev3_count"] == 0
    assert len(after_failure["new_actions"]) == 2
    assert len(after_failure["new_evidence_ids"]) == 2
    assert after_failure["trace_counts"] == {"WRITE_PLAN_SAVED": 1}
    assert [row[0:2] for row in after_failure["command_receipts"]] == [
        ("SaveWritePlan", "APPLIED"),
    ]
    assert state["__reserved_corrective_plan_id__"] == "reserved-plan-2"
    assert harness.save_calls == 1
    assert harness.publish_calls == 1

    assert _persist(harness, state, draft) == "reserved-plan-2"
    assert harness.save_calls == 1
    assert harness.publish_calls == 2
    assert state["__reserved_corrective_plan_id__"] is None

    _assert_published_snapshot(_aggregate_snapshot(database_path))


@pytest.mark.parametrize("drift_kind", ["arguments", "dependency", "evidence"])
def test_candidate_drift_after_committed_save_fails_closed(
    tmp_path: Path,
    drift_kind: str,
) -> None:
    database_path = tmp_path / f"corrective-drift-{drift_kind}.db"
    harness, state, draft = _prepare(database_path, fail_publish_once=True)

    with pytest.raises(RuntimeError, match="injected publish failure"):
        _persist(harness, state, draft)

    drifted = deepcopy(draft)
    if drift_kind == "arguments":
        drifted["actions"][0]["arguments"] = {"draft_id": "drifted-draft"}
    elif drift_kind == "dependency":
        drifted["actions"][1]["depends_on_action_ids"] = []
    else:
        drifted["actions"][1]["evidence_refs"] = ["old-evidence-1"]
        drifted["evidence_refs"] = ["old-evidence-1"]

    with pytest.raises(ValueError, match="Save receipt|persisted corrective"):
        _persist(harness, state, drifted)

    after_drift = _aggregate_snapshot(database_path)
    assert after_drift["plans"] == [
        ("old-plan", 1, "SUPERSEDED"),
        ("reserved-plan-2", 2, "DRAFT"),
    ]
    assert after_drift["run_status"] == "PLANNING"
    assert after_drift["rev3_count"] == 0
    assert len(after_drift["new_actions"]) == 2
    assert len(after_drift["new_evidence_ids"]) == 2
    assert after_drift["trace_counts"] == {"WRITE_PLAN_SAVED": 1}
    assert harness.save_calls == 1
    assert harness.publish_calls == 1
    assert state["__reserved_corrective_plan_id__"] == "reserved-plan-2"


def test_already_published_replay_has_no_second_save_or_publish_side_effect(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "corrective-published-replay.db"
    harness, state, draft = _prepare(database_path)

    assert _persist(harness, state, draft) == "reserved-plan-2"
    first_snapshot = _aggregate_snapshot(database_path)
    assert harness.save_calls == 1
    assert harness.publish_calls == 1

    # Simulate a stale checkpoint that survived after the durable Publish
    # commit but before the one-shot marker update was checkpointed.
    state["__reserved_corrective_plan_id__"] = "reserved-plan-2"
    assert _persist(harness, state, draft) == "reserved-plan-2"

    assert state["__reserved_corrective_plan_id__"] is None
    assert harness.save_calls == 1
    assert harness.publish_calls == 1
    second_snapshot = _aggregate_snapshot(database_path)
    assert second_snapshot == first_snapshot
    _assert_published_snapshot(second_snapshot)


def test_reserved_corrective_marker_survives_failed_compiled_checkpoint_and_is_consumed(
    tmp_path: Path,
) -> None:
    """The internal marker is checkpointed across a failed node and cleared on retry."""

    attempts = 0

    def persist_node(state: ParentGraphState) -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        assert state["__reserved_corrective_plan_id__"] == "reserved-plan-2"
        if attempts == 1:
            raise RuntimeError("injected node failure")
        return {"__reserved_corrective_plan_id__": None}

    builder = StateGraph(ParentGraphState)
    builder.add_node("persist", persist_node)
    builder.add_edge(START, "persist")
    builder.add_edge("persist", END)

    connection = sqlite3.connect(
        tmp_path / "corrective-checkpoint.db",
        check_same_thread=False,
    )
    try:
        graph = builder.compile(checkpointer=SqliteSaver(connection))
        config: RunnableConfig = {"configurable": {"thread_id": "corrective-thread"}}
        initial_state = cast(
            ParentGraphState,
            {
                "run_id": "run-1",
                "__reserved_corrective_plan_id__": "reserved-plan-2",
            },
        )

        with pytest.raises(RuntimeError, match="injected node failure"):
            graph.invoke(initial_state, config=config)

        failed_snapshot = graph.get_state(config)
        assert failed_snapshot.values["__reserved_corrective_plan_id__"] == "reserved-plan-2"
        assert failed_snapshot.next == ("persist",)

        graph.invoke(None, config=config)
        completed_snapshot = graph.get_state(config)
        assert completed_snapshot.values["__reserved_corrective_plan_id__"] is None
        assert completed_snapshot.next == ()
        assert attempts == 2
    finally:
        connection.close()
