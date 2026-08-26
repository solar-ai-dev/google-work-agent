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
    source = (ROOT / "launcher/dev.py").read_text(encoding="utf-8")

    assert "coordinator.enqueue_start" not in source
    assert "materialize_admission_checkpoint=_materialize_admission_checkpoint" in source
    assert "checkpoint.execution_scope(" in source


def test_workflow_binding_has_one_contract_and_sql_owner() -> None:
    contract = ROOT / "ports/system/contracts/workflow_binding.py"
    sql_owner = ROOT / "adapters/system/sqlite_checkpoint.py"
    offenders: list[Path] = []

    assert "class WorkflowBindingV1" in contract.read_text(encoding="utf-8")
    for path in ROOT.rglob("*.py"):
        if path == sql_owner:
            continue
        source = path.read_text(encoding="utf-8")
        if (
            "INSERT INTO workflow_bindings" in source
            or "CREATE TABLE IF NOT EXISTS workflow_bindings" in source
        ):
            offenders.append(path)
    assert offenders == []


def test_start_run_binding_uses_transaction_scoped_checkpoint_adapter() -> None:
    start_run = (ROOT / "application/use_cases/run/start_run.py").read_text(encoding="utf-8")
    unit_of_work = (ROOT / "adapters/persistence/sqlite/unit_of_work.py").read_text(
        encoding="utf-8"
    )
    launcher = (ROOT / "launcher/dev.py").read_text(encoding="utf-8")

    assert "unit_of_work.checkpoints.create_workflow_binding(" in start_run
    assert "SqliteCheckpointAdapter.for_transaction(" in unit_of_work
    assert 'root / "langgraph-checkpoints.sqlite3"' not in launcher
    assert "checkpoint = SqliteCheckpointAdapter(" in launcher
