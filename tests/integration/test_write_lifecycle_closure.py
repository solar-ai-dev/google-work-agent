"""Write lifecycle integration closure contracts."""

from __future__ import annotations

import inspect

import google_work_agent.adapters.langgraph.corrective_plan_persistence as corrective_persistence
import google_work_agent.adapters.langgraph.main.plan_persistence as plan_persistence
from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.adapters.langgraph.main.workflow import (
    LangGraphWorkflowRuntime,
)
from google_work_agent.adapters.persistence.sqlite.repositories.plan_repository import (
    SqlitePlanRepository,
)
from google_work_agent.application.use_cases.recovery.resolve_recovery import ResolveRecoveryHandler
from google_work_agent.application.use_cases.run.block_run import BlockRunHandler


def test_block_run_cleanup_is_single_uow_and_trigger_safe() -> None:
    transition_source = inspect.getsource(BlockRunHandler.__call__)
    cleanup_source = inspect.getsource(BlockRunHandler._settle_children)

    assert "_settle_children" in transition_source
    assert "unit_of_work.commit()" not in cleanup_source
    revoke_at = cleanup_source.index("revoke_active_approvals")
    terminal_at = cleanup_source.index("update_action_record")
    cancel_at = cleanup_source.index("update_plan_record")
    assert revoke_at < terminal_at < cancel_at


def test_corrective_recovery_reserves_durable_plan_without_runtime_payload_authority() -> None:
    source = inspect.getsource(ResolveRecoveryHandler._apply_resolution_effects)

    assert '"CORRECTIVE_PLAN_REQUIRED"' in source
    assert "unit_of_work.plans.insert_revision(corrective)" in source
    assert "resume_target" not in source


def test_corrective_runtime_uses_profile_translated_planning_target() -> None:
    source = inspect.getsource(LangGraphWorkflowRuntime._resume_corrective_plan)

    assert "SupervisorTarget.SOLUTION_PLANNING.value" in source
    assert "_route_translator.translate" in source
    assert 'as_node="recovery"' in source
    assert 'resume_payload.get("plan_id")' in source
    assert '"__reserved_corrective_plan_id__": plan.id' in source
    assert '"__replan_from_plan_id__": None' in source
    assert "__reserved_corrective_plan_id__" in GraphState.__annotations__
    assert 'resume_payload.get("target")' not in source
    assert "resume_target" not in source


def test_corrective_resume_retries_pending_non_interrupt_task_and_reconciles_publish() -> None:
    source = inspect.getsource(LangGraphWorkflowRuntime._resume_corrective_plan)

    assert "has_pending_interrupt" in source
    assert "if snapshot.next:" in source
    assert 'state.get("__reserved_corrective_plan_id__") != plan.id' in source
    assert "self._graph.invoke(None, config=config)" in source
    assert "RunStatusV1.WAITING_APPROVAL" in source
    assert "PlanStatusV1.WAITING_APPROVAL" in source
    assert '"__reserved_corrective_plan_id__": None' in source
    assert "WorkflowPhase.WAITING_APPROVAL.value" in source


def test_corrective_persistence_separates_reserved_plan_from_child_remapping() -> None:
    ordinary_source = inspect.getsource(plan_persistence.PlanPersistenceMixin._persist_write_plan)
    corrective_source = inspect.getsource(corrective_persistence)
    runtime_source = inspect.getsource(LangGraphWorkflowRuntime._persist_write_plan)
    repository_source = inspect.getsource(SqlitePlanRepository.insert_revision)

    # Ordinary replan semantics remain untouched.
    assert "reserved_plan" not in ordinary_source
    assert "__reserved_corrective_plan_id__" not in ordinary_source

    # Corrective persistence fixes the destination revision while using stable,
    # revision-local child identities. Retry does not allocate fresh random
    # children or blindly invoke Save again.
    assert "reserved_plan.id" in corrective_source
    assert "reserved_plan.revision_no" in corrective_source
    assert "_corrective_child_id" in corrective_source
    assert "action_id_map" in corrective_source
    assert "evidence_id_map" in corrective_source
    assert "depends_on_action_ids" in corrective_source
    assert "persisted_connector_ids" in corrective_source
    assert "_continue_durable_corrective_write_plan" in corrective_source
    assert "if existing_actions:" in corrective_source
    assert "if use_durable_continuation:" in corrective_source
    assert "resolve_evidence_projection" in corrective_source

    # The one-shot marker is consumed only after verified Publish success or
    # verified already-published replay.
    assert 'state["__reserved_corrective_plan_id__"] = None' in runtime_source
    assert "verified already-published replay" in runtime_source

    # Repository reuse remains limited to the exact empty reserved revision.
    assert "existing.revision_no != plan.revision_no" in repository_source
    assert "exact empty reserved corrective draft" in repository_source
