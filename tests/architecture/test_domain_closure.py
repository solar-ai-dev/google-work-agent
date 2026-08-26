from __future__ import annotations

import ast
from importlib import import_module
from inspect import Parameter, signature
from pathlib import Path

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


def test_removed_lifecycle_authorities_are_absent() -> None:
    assert all(not path.exists() for path in REMOVED_AUTHORITIES)


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
        SRC
        / "adapters"
        / "persistence"
        / "sqlite"
        / "repositories"
        / "verification_repository.py",
    )
    methods: set[str] = set()
    for path in repository_files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        methods.update(node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef))
    assert methods.isdisjoint(FORBIDDEN_REPOSITORY_METHODS)
