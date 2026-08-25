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
