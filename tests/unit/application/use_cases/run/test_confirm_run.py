"""Exact ownership smoke gate for the canonical Application module."""

from dataclasses import asdict
from json import dumps
from pathlib import Path

from tests.support.checkpoint import sqlite_checkpoint

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.agents.work_analysis.assemble_work_analysis import (
    work_analysis_confirmation_context_hash,
)
from google_work_agent.application.use_cases.run.confirm_run import (
    ConfirmRunCommand,
    ConfirmRunHandler,
)
from google_work_agent.application.use_cases.run.resume_confirmation import (
    ResumeConfirmationHandler,
    ResumeConfirmationResult,
)
from google_work_agent.domain.results import ResultCode


def test_work_analysis_override_confirmation_creates_bound_policy_receipt() -> None:
    handler = ConfirmRunHandler(
        resolve_pending_confirmation=lambda _run_id: None,
        resume_confirmation=object(),  # type: ignore[arg-type]
        resume_target_registry=object(),  # type: ignore[arg-type]
        schedule_run_execution=lambda _command: (_ for _ in ()).throw(AssertionError("not used")),
        id_factory=lambda: "receipt-1",
    )
    based_on = [{"artifact_id": "candidate-1", "revision": 2}]
    authority = {
        "interrupt_id": "interrupt-1",
        "policy_confirmation": {
            "confirmation_kind": "DUPLICATE_OVERRIDE",
            "based_on": based_on,
        },
    }

    receipt = handler._policy_receipt(
        authority,
        {
            "schema_version": 1,
            "response_kind": "OPTION",
            "selected_option": "APPROVED",
            "free_text": None,
        },
    )

    assert receipt is not None
    assert receipt["confirmation_kind"] == "DUPLICATE_OVERRIDE"
    assert receipt["decision"] == "APPROVED"
    assert receipt["semantic_owner_id"] == "WORK_ANALYSIS"
    assert receipt["meta"] == {
        "artifact_id": "receipt-1",
        "revision": 1,
        "based_on": based_on,
    }
    assert receipt["decision_context_hash"] == work_analysis_confirmation_context_hash(
        confirmation_kind="DUPLICATE_OVERRIDE",
        interrupt_id="interrupt-1",
        based_on=based_on,  # type: ignore[arg-type]
    )


def test_prior_confirmation_receipt_replays_before_live_interrupt_lookup() -> None:
    class _Resume:
        def replay_existing(self, **_identity: object) -> ResumeConfirmationResult:
            return ResumeConfirmationResult(
                True,
                "TRANSITION_APPLIED",
                "run-1",
                "ANALYZING",
                2,
                None,
                True,
            )

    handler = ConfirmRunHandler(
        resolve_pending_confirmation=lambda _run_id: (_ for _ in ()).throw(
            AssertionError("live interrupt lookup must not run for a durable replay")
        ),
        resume_confirmation=_Resume(),  # type: ignore[arg-type]
        resume_target_registry=object(),  # type: ignore[arg-type]
        schedule_run_execution=lambda _command: (_ for _ in ()).throw(
            AssertionError("a replay must not enqueue a second handoff")
        ),
        id_factory=lambda: "unused",
    )

    result = handler(
        ConfirmRunCommand("cmd-1", "a" * 64, "run-1", 1, "interrupt-1", "OPTION", "yes", None)
    )

    assert result.applied
    assert result.request_replayed
    assert result.run_status == "ANALYZING"


def test_applied_confirmation_remains_replayable_after_later_run_state_change(
    tmp_path: Path,
) -> None:
    path = tmp_path / "confirm-replay.db"
    with connect_sqlite(path) as connection:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('a-1', 'u@example.com', NULL, 1, NULL);"
        )
        connection.execute("INSERT INTO conversations VALUES ('c-1', 'a-1', 'Test', 1, 1);")
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, actual_runtime, budget_json, version, started_at_ms, finished_at_ms
            ) VALUES ('run-1', 'c-1', 'AGENT_SEARCH', 'PLANNING', 't-1',
                      'AUTO', NULL, '{}', 3, 1, NULL);
            """
        )
        connection.commit()
    factory = sqlite_unit_of_work_factory(path, now_ms=lambda: 10)
    durable = ResumeConfirmationResult(
        True, "TRANSITION_APPLIED", "run-1", "ANALYZING", 2, "handoff-1", False
    )
    with factory() as unit_of_work:
        unit_of_work.command_receipts.reserve_or_replay(
            command_id="cmd-durable",
            command_type="ResumeConfirmation",
            request_hash="a" * 64,
            aggregate_type="Run",
            aggregate_id="run-1",
            created_at_ms=1,
        )
        unit_of_work.command_receipts.store_result(
            command_id="cmd-durable",
            applied=True,
            result_code=ResultCode.TRANSITION_APPLIED,
            result_version=2,
            response_json=dumps(asdict(durable), sort_keys=True),
            completed_at_ms=2,
        )
        unit_of_work.commit()
    resume = ResumeConfirmationHandler(
        unit_of_work_factory=factory,
        checkpoint_port=sqlite_checkpoint(path),
        now_ms=lambda: 10,
        id_factory=lambda: "unused",
        resume_target_registry=object(),  # type: ignore[arg-type]
    )
    handler = ConfirmRunHandler(
        resolve_pending_confirmation=lambda _run_id: (_ for _ in ()).throw(
            AssertionError("mutable interrupt state must not precede Receipt replay")
        ),
        resume_confirmation=resume,
        resume_target_registry=object(),  # type: ignore[arg-type]
        schedule_run_execution=lambda _command: (_ for _ in ()).throw(
            AssertionError("replay must not enqueue")
        ),
        id_factory=lambda: "unused",
    )

    result = handler(
        ConfirmRunCommand(
            "cmd-durable",
            "a" * 64,
            "run-1",
            1,
            "interrupt-stale",
            "OPTION",
            "stale",
            None,
        )
    )

    assert result.applied
    assert result.request_replayed
    assert (result.run_status, result.run_version) == ("ANALYZING", 2)
