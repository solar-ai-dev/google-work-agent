"""Write lifecycle integration closure contracts."""

from __future__ import annotations

import inspect

from google_work_agent.adapters.langgraph.canonical_freshness_runtime import (
    LangGraphWorkflowRuntime,
)
from google_work_agent.adapters.langgraph.canonical_planning_runtime import (
    LangGraphWorkflowRuntime as CanonicalPlanningRuntime,
)
from google_work_agent.adapters.persistence.corrective_plan_repository import (
    CorrectiveAwareSQLitePlanRepository,
)
from google_work_agent.api.routes.runs import resolve_recovery
from google_work_agent.application import run_terminal


def test_block_run_cleanup_is_single_uow_and_trigger_safe() -> None:
    transition_source = inspect.getsource(run_terminal._apply_run_transition)
    cleanup_source = inspect.getsource(run_terminal._cleanup_plans_for_block)

    assert "_cleanup_plans_for_block" in transition_source
    assert "unit_of_work.commit()" not in cleanup_source
    revoke_at = cleanup_source.index("revoke_active_by_action")
    terminal_at = cleanup_source.index("mark_dependency_blocked")
    cancel_at = cleanup_source.index("plans.cancel")
    assert revoke_at < terminal_at < cancel_at


def test_corrective_recovery_api_enqueues_only_registered_internal_resume_kind() -> None:
    source = inspect.getsource(resolve_recovery)

    assert 'result.result_kind == "CORRECTIVE_PLAN_REQUIRED"' in source
    assert 'resume_kind="RECOVERY_CORRECTIVE_PLAN"' in source
    assert 'resume_payload={"plan_id": result.plan_id}' in source
    assert "resume_target" not in source


def test_corrective_runtime_uses_profile_translated_planning_target() -> None:
    source = inspect.getsource(LangGraphWorkflowRuntime._resume_corrective_plan)

    assert "SupervisorTarget.PLANNING.value" in source
    assert "_route_translator.translate" in source
    assert 'as_node="recovery"' in source
    assert 'resume_payload.get("plan_id")' in source
    assert 'resume_payload.get("target")' not in source
    assert "resume_target" not in source


def test_corrective_reserved_draft_is_reused_not_revised_again() -> None:
    planning_source = inspect.getsource(CanonicalPlanningRuntime._persist_write_plan)
    repository_source = inspect.getsource(CorrectiveAwareSQLitePlanRepository.insert_draft)

    assert "reserved_plan.status is PlanStatus.DRAFT" in planning_source
    assert 'deterministic_plan["plan_id"] = reserved_plan.id' in planning_source
    assert '"__replan_from_plan_id__": None' in planning_source
    assert "empty reserved corrective draft" in repository_source
    assert "UPDATE plans SET summary_text" in repository_source
