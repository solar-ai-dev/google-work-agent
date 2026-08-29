from __future__ import annotations

import ast
from importlib import import_module
from inspect import Parameter, signature
from pathlib import Path
from typing import get_args

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "google_work_agent"
DOMAIN = SRC / "domain"

MODEL_AUTHORITIES = {
    "conversation.model": ("Conversation",),
    "message.model": ("Message",),
    "run.model": ("Run",),
    "plan.model": ("Plan",),
    "action.model": ("Action", "ActionDependency", "ActionEvidence"),
    "approval.model": ("Approval",),
    "execution_attempt.model": ("ExecutionAttempt",),
    "verification.model": ("Verification",),
    "resource_ref.model": ("ResourceRef",),
    "evidence.model": ("Evidence",),
    "command_receipt.model": ("CommandReceipt",),
    "trace_event.model": ("TraceEvent",),
    "audit_event.model": ("AuditEvent",),
}

VOCABULARY_AUTHORITIES = {
    "run.model": "RunStatusV1",
    "action.model": "ActionStatusV1",
    "plan.model": "PlanStatusV1",
    "approval.model": "ApprovalStatusV1",
    "execution_attempt.model": "ExecutionAttemptStatusV1",
    "recovery.model": "RecoveryReasonV1",
}

TRANSITION_AUTHORITIES = {
    "run.start_run",
    "run.start_analysis",
    "run.begin_retrieval",
    "run.begin_planning",
    "run.request_confirmation",
    "run.resume_confirmation",
    "run.complete_answer_only_run",
    "run.complete_read_only_run",
    "run.block_run",
    "run.begin_verification",
    "run.complete_write_run",
    "run.request_cancel",
    "run.finalize_cancel",
    "run.require_reauth",
    "run.resume_after_reauth",
    "plan.publish_plan",
    "plan.publish_read_only_plan",
    "recovery.require_recovery",
    "recovery.resolve_recovery",
    "action.approve_action",
    "action.modify_action",
    "action.reject_action",
    "action.cancel_pending_action",
    "action.refresh_expired_action",
    "action.claim_read_action",
    "action.complete_read_action",
    "action.finalize_read_action",
    "action.fail_read_action",
    "action.prepare_write_retry",
    "approval.expire_approval",
    "claim.claim_execution",
    "execution_attempt.begin_execution_attempt",
    "execution_attempt.abort_claimed_execution",
    "execution_attempt.store_success",
    "execution_attempt.mark_failed",
    "execution_attempt.mark_unknown_result",
    "execution_attempt.recover_existing_result",
    "execution_attempt.resolve_as_failed",
    "verification.store_verification",
}

GUARD_AUTHORITIES = {
    "action.current_plan_authority",
    "claim.claim_execution",
    "recovery.require_recovery",
    "recovery.resolve_recovery",
    "run.begin_planning",
    "run.begin_retrieval",
    "run.block_run",
    "run.complete_answer_only_run",
    "run.complete_write_run",
    "run.finalize_cancel",
    "run.request_cancel",
    "run.request_confirmation",
    "run.require_reauth",
    "run.resume_after_reauth",
    "run.resume_confirmation",
    "run.start_analysis",
    "run.start_run",
}

APPLICATION_OWNER_AUTHORITIES = {
    "run.complete_answer_only_run": "CompleteAnswerOnlyRunHandler",
    "run.complete_read_only_run": "CompleteReadOnlyRunHandler",
    "run.begin_verification": "BeginVerificationHandler",
    "run.complete_write_run": "CompleteWriteRunHandler",
    "run.finalize_cancel": "FinalizeCancelHandler",
    "run.require_reauth": "RequireReauthHandler",
    "run.resume_after_reauth": "ResumeAfterReauthHandler",
    "run.block_run": "BlockRunHandler",
    "plan.publish_plan": "PublishPlanHandler",
    "plan.publish_read_only_plan": "PublishReadOnlyPlanHandler",
    "action.approve_action": "ApproveActionHandler",
    "action.modify_action": "ModifyActionHandler",
    "action.reject_action": "RejectActionHandler",
    "action.cancel_pending_action": "CancelPendingActionHandler",
    "action.refresh_expired_action": "RefreshExpiredActionHandler",
    "action.claim_read_action": "ClaimReadActionHandler",
    "action.complete_read_action": "CompleteReadActionHandler",
    "action.finalize_read_action": "FinalizeReadActionHandler",
    "action.fail_read_action": "FailReadActionHandler",
    "approval.expire_approval": "ExpireApprovalHandler",
    "execution_attempt.begin_execution_attempt": "BeginExecutionAttemptHandler",
    "execution_attempt.abort_claimed_execution": "AbortClaimedExecutionHandler",
}

REMOVED_AUTHORITIES = (
    DOMAIN / "enums.py",
    DOMAIN / "exceptions.py",
    SRC / "ports" / "models.py",
    SRC / "ports" / "repositories.py",
    DOMAIN / "run" / "transitions" / "run.py",
    DOMAIN / "action" / "transitions" / "action.py",
    DOMAIN / "run" / "transitions" / "publish_plan.py",
    DOMAIN / "approval" / "transitions" / "approve_action.py",
    DOMAIN / "approval" / "transitions" / "consume_approval.py",
    DOMAIN / "approval" / "transitions" / "revoke_approval.py",
    DOMAIN / "action" / "queries.py",
    DOMAIN / "run" / "queries.py",
    DOMAIN / "execution_attempt" / "transitions" / "decision.py",
    DOMAIN / "policy_confirmation_receipt" / "__init__.py",
    DOMAIN / "action_risk.py",
    DOMAIN / "calendar_conflict.py",
    DOMAIN / "feasibility.py",
    DOMAIN / "task_duplicate.py",
    DOMAIN / "policy.py",
    DOMAIN / "tool_registry.py",
    DOMAIN / "google_workspace_tool_registry.py",
    DOMAIN / "google_workspace_project_registry.py",
    DOMAIN / "claim_contract.py",
    SRC / "application" / "answer_only.py",
    SRC / "application" / "read_lifecycle.py",
    SRC / "application" / "write_reauth.py",
    SRC / "application" / "write_run_completion.py",
    SRC / "application" / "write_approval.py",
    SRC / "application" / "write_action_mutation.py",
)

FORBIDDEN_IMPORT_PREFIXES = (
    "google_work_agent.application",
    "google_work_agent.adapters",
    "google_work_agent.api",
    "google_work_agent.ports",
)

FORBIDDEN_REPOSITORY_METHODS = {
    "approve_write",
    "modify_write",
    "reject_write",
    "cancel_pending_action",
    "claim_execution",
    "complete_write_run",
    "complete_read_only_run",
    "publish_plan",
    "publish_read_only_plan",
    "require_reauth",
    "require_recovery",
    "resolve_recovery",
    "store_verification",
    "prepare_write_retry",
}


@pytest.mark.parametrize(("module_name", "symbols"), MODEL_AUTHORITIES.items())
def test_all_fifteen_models_have_owner_local_authority(
    module_name: str, symbols: tuple[str, ...]
) -> None:
    module = import_module(f"google_work_agent.domain.{module_name}")
    for symbol in symbols:
        assert getattr(module, symbol).__module__ == module.__name__


def test_closed_owner_vocabularies_have_no_legacy_family_or_observation_values() -> None:
    resource_ref = import_module("google_work_agent.domain.resource_ref.model")
    verification = import_module("google_work_agent.domain.verification.model")
    assert not hasattr(resource_ref, "StoredResourceType")
    assert {status.value for status in verification.VerificationStatus} == {
        "VERIFIED",
        "MISMATCH",
    }


def test_all_six_closed_vocabularies_use_exact_versioned_symbols() -> None:
    for module_name, symbol in VOCABULARY_AUTHORITIES.items():
        module = import_module(f"google_work_agent.domain.{module_name}")
        vocabulary = getattr(module, symbol)
        assert get_args(vocabulary) or vocabulary.__module__ == module.__name__
        assert not hasattr(module, symbol.removesuffix("V1"))


def test_exact_transition_tree_has_thirty_nine_mirrored_operations() -> None:
    sources = sorted(
        path
        for path in DOMAIN.glob("*/transitions/*.py")
        if path.name not in {"__init__.py", "decision.py"}
    )
    mirrors = sorted(
        path for path in (ROOT / "tests" / "unit" / "domain").glob("*/transitions/test_*.py")
    )
    assert len(sources) == 39
    assert len(mirrors) == 39
    expected_mirrors = {path.relative_to(DOMAIN).with_name(f"test_{path.name}") for path in sources}
    actual_mirrors = {path.relative_to(ROOT / "tests" / "unit" / "domain") for path in mirrors}
    assert actual_mirrors == expected_mirrors
    actual_authorities = {
        ".".join(path.relative_to(DOMAIN).with_suffix("").parts).replace(".transitions.", ".")
        for path in sources
    }
    assert actual_authorities == TRANSITION_AUTHORITIES


def test_required_guard_tree_has_seventeen_mirrored_behavioral_owners() -> None:
    sources = sorted(path for path in DOMAIN.glob("*/guards/*.py") if path.name != "__init__.py")
    mirrors = sorted(
        path for path in (ROOT / "tests" / "unit" / "domain").glob("*/guards/test_*.py")
    )
    assert len(sources) == 17
    assert len(mirrors) == 17
    expected_mirrors = {path.relative_to(DOMAIN).with_name(f"test_{path.name}") for path in sources}
    actual_mirrors = {path.relative_to(ROOT / "tests" / "unit" / "domain") for path in mirrors}
    assert actual_mirrors == expected_mirrors
    actual_authorities = {
        ".".join(path.relative_to(DOMAIN).with_suffix("").parts).replace(".guards.", ".")
        for path in sources
    }
    assert actual_authorities == GUARD_AUTHORITIES


def test_formal_domain_ledger_universe_is_exactly_sixty_one_rows() -> None:
    assert (
        1
        + sum(map(len, MODEL_AUTHORITIES.values()))
        + len(VOCABULARY_AUTHORITIES)
        + len(TRANSITION_AUTHORITIES)
        == 61
    )


@pytest.mark.parametrize(("owner", "handler"), APPLICATION_OWNER_AUTHORITIES.items())
def test_corrected_domain_callers_have_exact_application_owner_and_test(
    owner: str, handler: str
) -> None:
    module = import_module(f"google_work_agent.application.use_cases.{owner}")
    assert getattr(module, handler).__module__ == module.__name__
    owner_name, operation = owner.split(".")
    test_path = (
        ROOT / "tests" / "unit" / "application" / "use_cases" / owner_name / f"test_{operation}.py"
    )
    assert test_path.is_file()


def test_removed_lifecycle_authorities_are_absent() -> None:
    assert all(not path.exists() for path in REMOVED_AUTHORITIES)


def test_corrected_action_commands_have_no_legacy_production_caller_or_export() -> None:
    forbidden_symbols = {
        "ApproveWriteActionService",
        "ModifyWriteActionService",
        "RejectWriteActionService",
    }
    violations: list[str] = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in forbidden_symbols:
                violations.append(f"{path.relative_to(ROOT)}:{node.id}")
            if isinstance(node, ast.Attribute) and node.attr in forbidden_symbols:
                violations.append(f"{path.relative_to(ROOT)}:{node.attr}")
    assert violations == []


def test_every_domain_transition_authority_is_owner_local_and_exact() -> None:
    violations = []
    for path in DOMAIN.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        transition_functions = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("transition_")
        ]
        if transition_functions and path.parent.name != "transitions":
            violations.append(str(path.relative_to(ROOT)))
    assert violations == []


@pytest.mark.parametrize(
    "module_name",
    (
        "action.transitions.approve_action",
        "action.transitions.cancel_pending_action",
        "action.transitions.modify_action",
        "action.transitions.prepare_write_retry",
        "action.transitions.refresh_expired_action",
        "action.transitions.reject_action",
        "approval.transitions.expire_approval",
    ),
)
def test_child_mutations_require_explicit_current_plan_facts(module_name: str) -> None:
    module = import_module(f"google_work_agent.domain.{module_name}")
    operation = next(
        value
        for name, value in vars(module).items()
        if name.startswith("transition_") and callable(value)
    )
    parameters = signature(operation).parameters
    if module_name == "approval.transitions.expire_approval":
        expiry_input = module.ApprovalExpiryInput
        annotations = expiry_input.__annotations__
        assert "plan_status" in annotations
        assert "plan_is_current" in annotations
        return
    assert parameters["plan_status"].default is Parameter.empty
    assert parameters["plan_is_current"].default is Parameter.empty


def test_domain_has_no_outward_layer_imports() -> None:
    violations: list[str] = []
    for path in DOMAIN.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module = node.module if isinstance(node, ast.ImportFrom) else None
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else ([module] if module else [])
            )
            for name in names:
                if name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                    violations.append(f"{path.relative_to(ROOT)}:{name}")
    assert violations == []


def test_domain_package_barrel_exports_no_concrete_authority() -> None:
    module = import_module("google_work_agent.domain")
    assert module.__all__ == ()
    tree = ast.parse((DOMAIN / "__init__.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in tree.body)


def test_lifecycle_repositories_expose_only_query_persistence_and_cas() -> None:
    repository_files = (
        SRC / "ports" / "persistence" / "run_repository.py",
        SRC / "ports" / "persistence" / "action_repository.py",
        SRC / "ports" / "persistence" / "plan_repository.py",
        SRC / "ports" / "persistence" / "approval_repository.py",
        SRC / "ports" / "persistence" / "execution_attempt_repository.py",
        SRC / "ports" / "persistence" / "verification_repository.py",
        SRC / "adapters" / "persistence" / "sqlite" / "repositories" / "run_repository.py",
        SRC / "adapters" / "persistence" / "sqlite" / "repositories" / "action_repository.py",
        SRC / "adapters" / "persistence" / "sqlite" / "repositories" / "plan_repository.py",
        SRC / "adapters" / "persistence" / "sqlite" / "repositories" / "approval_repository.py",
        SRC
        / "adapters"
        / "persistence"
        / "sqlite"
        / "repositories"
        / "execution_attempt_repository.py",
        SRC / "adapters" / "persistence" / "sqlite" / "repositories" / "verification_repository.py",
    )
    methods: set[str] = set()
    for path in repository_files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        methods.update(node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef))
    assert methods.isdisjoint(FORBIDDEN_REPOSITORY_METHODS)
