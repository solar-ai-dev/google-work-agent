from pathlib import Path

ROOT = Path(__file__).parents[2] / "src" / "google_work_agent"


def test_run_phase_handlers_depend_only_on_domain_and_ports() -> None:
    for name in ("start_analysis.py", "begin_retrieval.py", "begin_planning.py"):
        source = (ROOT / "application" / "use_cases" / "run" / name).read_text(encoding="utf-8")
        assert "google_work_agent.adapters" not in source
        assert "google_work_agent.ports.repositories" not in source
        assert "update_if_version_and_status(" in source


def test_run_repository_has_no_phase_transition_command_authority() -> None:
    repository_sources = (
        ROOT / "ports" / "persistence" / "run_repository.py",
        ROOT / "adapters" / "persistence" / "sqlite" / "repositories" / "run_repository.py",
    )
    for path in repository_sources:
        source = path.read_text(encoding="utf-8")
        for method in (
            "def start_analysis(",
            "def begin_retrieval(",
            "def begin_planning(",
            "def replan(",
        ):
            assert method not in source
    assert not (ROOT / "adapters" / "persistence" / "repositories.py").exists()


def test_workflow_uses_explicit_phase_handlers_without_dynamic_repository_dispatch() -> None:
    source = (ROOT / "adapters" / "langgraph" / "main" / "workflow.py").read_text(encoding="utf-8")
    assert "services.start_analysis" in source
    assert "services.begin_retrieval" in source
    assert "services.begin_planning" in source
    assert "StartAnalysisHandler(" not in source
    assert "BeginRetrievalHandler(" not in source
    assert "BeginPlanningHandler(" not in source
    assert "getattr(unit_of_work.runs" not in source
    assert ".runs.replan(" not in source


def test_superseded_plan_children_cannot_regain_mutation_or_execution_authority() -> None:
    guarded_operations = (
        ROOT / "application" / "use_cases" / "action" / "modify_action.py",
        ROOT / "application" / "use_cases" / "action" / "approve_action.py",
        ROOT / "application" / "use_cases" / "action" / "prepare_write_retry.py",
    )
    for path in guarded_operations:
        source = path.read_text(encoding="utf-8")
        assert "PlanStatusV1.SUPERSEDED" in source
        assert "superseded Plan children are history-only" in source
    claim = (ROOT / "application" / "use_cases" / "claim" / "claim_execution.py").read_text(
        encoding="utf-8"
    )
    assert "plan_status=plan.status" in claim
    assert "plan_is_current=current_plan is not None and current_plan.id == plan.id" in claim
