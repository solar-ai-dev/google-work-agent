from pathlib import Path

ROOT = Path("src/google_work_agent")


def test_workflow_handoff_sql_mutation_is_owned_only_by_canonical_repository() -> None:
    allowed = {
        ROOT / "adapters/persistence/sqlite/repositories/workflow_handoff_repository.py",
        ROOT / "adapters/persistence/migrations/0009_workflow_handoff_outbox.sql",
    }
    offenders: list[Path] = []
    for path in (*ROOT.rglob("*.py"), *ROOT.rglob("*.sql")):
        if path in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if "UPDATE workflow_handoffs" in text or "INSERT INTO workflow_handoffs" in text:
            offenders.append(path)
    assert offenders == []


def test_application_scheduler_never_imports_concrete_execution_adapter() -> None:
    source = (ROOT / "application/use_cases/run/schedule_run_execution.py").read_text(
        encoding="utf-8"
    )
    assert "adapters." not in source


def test_local_coordinator_has_no_start_or_open_run_recovery_authority() -> None:
    assert not (ROOT / "application/coordinator.py").exists()


def test_launcher_never_reduces_admission_to_coordinator_start() -> None:
    source = (ROOT / "api/composition.py").read_text(encoding="utf-8")

    assert "coordinator.enqueue_start" not in source
    assert "materialize_admission_checkpoint=_materialize_admission_checkpoint" in source
    assert "checkpoint.execution_scope(" in source


def test_workflow_binding_has_one_contract_and_sql_owner() -> None:
    contract = ROOT / "ports/system/contracts/workflow_binding.py"
    sql_owners = {
        ROOT / "adapters/system/sqlite_checkpoint.py",
        ROOT / "adapters/persistence/sqlite/initial_workflow_binding_writer.py",
        ROOT / "adapters/persistence/migrations/0018_initial_workflow_binding.sql",
    }
    offenders: list[Path] = []

    assert "class WorkflowBindingV1" in contract.read_text(encoding="utf-8")
    for path in (*ROOT.rglob("*.py"), *ROOT.rglob("*.sql")):
        if path in sql_owners:
            continue
        source = path.read_text(encoding="utf-8")
        if (
            "INSERT INTO workflow_bindings" in source
            or "CREATE TABLE IF NOT EXISTS workflow_bindings" in source
        ):
            offenders.append(path)
    assert offenders == []


def test_start_run_binding_uses_narrow_transaction_writer_and_separate_checkpoint() -> None:
    start_run = (ROOT / "application/use_cases/run/start_run.py").read_text(encoding="utf-8")
    unit_of_work = (ROOT / "adapters/persistence/sqlite/unit_of_work.py").read_text(
        encoding="utf-8"
    )
    composition = (ROOT / "api/composition.py").read_text(encoding="utf-8")

    assert "unit_of_work.workflow_bindings.create_workflow_binding(" in start_run
    assert "unit_of_work.checkpoints" not in start_run
    assert "SqliteInitialWorkflowBindingWriter(connection)" in unit_of_work
    assert "SqliteCheckpointAdapter" not in unit_of_work
    assert 'root / "langgraph-checkpoints.sqlite3"' not in composition
    assert "checkpoint = SqliteCheckpointAdapter(" in composition


def test_retry_and_stale_preflight_use_durable_review_handoff_authority() -> None:
    retry = (ROOT / "application/use_cases/action/prepare_write_retry.py").read_text(
        encoding="utf-8"
    )
    preflight = (ROOT / "application/use_cases/action/write_preflight.py").read_text(
        encoding="utf-8"
    )

    assert 'issue_main_stage(\n            binding.graph_profile, "REVIEW_ENTRY"' in retry
    assert "workflow_handoffs.stage_pending(" in retry
    assert "ExpireApprovalCommand(" in preflight
    assert "RefreshExpiredActionCommand(" in preflight
    assert "transition_modify_action" not in preflight
    assert "revoke_active_approvals" not in preflight
