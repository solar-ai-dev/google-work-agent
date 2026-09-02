from pathlib import Path

from google_work_agent.adapters.persistence.sqlite.repositories import (
    execution_attempt_repository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.action_repository import (
    SqliteActionRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.approval_repository import (
    SqliteApprovalRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.audit_event_repository import (
    SqliteAuditEventRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.command_receipt_repository import (
    SqliteCommandReceiptRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.evidence_repository import (
    SqliteEvidenceRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.plan_repository import (
    SqlitePlanRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.retention_repository import (
    SqliteRetentionRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.run_repository import (
    SqliteRunRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.trace_event_repository import (
    SqliteTraceEventRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.verification_repository import (
    SqliteVerificationRepository,
)
from google_work_agent.ports.persistence.action_repository import ActionRepository
from google_work_agent.ports.persistence.approval_repository import ApprovalRepository
from google_work_agent.ports.persistence.audit_event_repository import AuditEventRepository
from google_work_agent.ports.persistence.command_receipt_repository import (
    CommandReceiptRepository,
)
from google_work_agent.ports.persistence.evidence_repository import EvidenceRepository
from google_work_agent.ports.persistence.execution_attempt_repository import (
    ExecutionAttemptRepository,
)
from google_work_agent.ports.persistence.plan_repository import PlanRepository
from google_work_agent.ports.persistence.retention_repository import RetentionRepository
from google_work_agent.ports.persistence.run_repository import RunRepository
from google_work_agent.ports.persistence.trace_event_repository import TraceEventRepository
from google_work_agent.ports.persistence.verification_repository import (
    VerificationRepository,
)

_ROOT = Path(__file__).resolve().parents[3]
_SOURCE = _ROOT / "src" / "google_work_agent"


def _methods(protocol: type[object]) -> set[str]:
    return {
        name
        for name, value in protocol.__dict__.items()
        if not name.startswith("_") and callable(value)
    }


def test_canonical_repository__ports_have__exact_public_surfaces() -> None:
    run_methods = {
        "create",
        "get",
        "get_snapshot",
        "find_open_by_conversation",
        "list_open_bounded",
        "update_if_version_and_status",
    }
    plan_methods = {
        "insert_revision",
        "get_current",
        "load_bundle",
        "record_review_result",
        "update_if_version_and_status",
    }
    action_methods = {
        "insert_for_plan",
        "get",
        "list_for_plan",
        "update_if_version_and_status",
        "list_dependents",
        "is_dependency_ready",
    }
    approval_methods = {
        "get",
        "insert_active_snapshot",
        "get_active_for_action",
        "list_for_action",
        "list_active_for_plan",
        "update_if_status",
    }
    attempt_methods = {
        "insert_claimed",
        "get",
        "get_active_for_approval",
        "list_reconciliation_candidates",
        "update_if_version_and_status",
    }
    verification_methods = {
        "insert",
        "get_latest_for_attempt",
        "list_for_action",
    }
    evidence_methods = {
        "insert_bounded",
        "list_for_run",
        "list_for_action",
    }
    receipt_methods = {
        "has_durable_cancel_intent",
        "get_by_command_id",
        "reserve_or_replay",
        "store_result",
    }
    assert _methods(RunRepository) == _methods(SqliteRunRepository) == run_methods
    assert _methods(PlanRepository) == _methods(SqlitePlanRepository) == plan_methods
    assert _methods(ActionRepository) == _methods(SqliteActionRepository) == action_methods
    assert _methods(ApprovalRepository) == _methods(SqliteApprovalRepository) == approval_methods
    assert (
        _methods(ExecutionAttemptRepository)
        == _methods(execution_attempt_repository.SqliteExecutionAttemptRepository)
        == attempt_methods
    )
    assert (
        _methods(VerificationRepository)
        == _methods(SqliteVerificationRepository)
        == verification_methods
    )
    assert _methods(EvidenceRepository) == _methods(SqliteEvidenceRepository) == evidence_methods
    assert (
        _methods(CommandReceiptRepository)
        == _methods(SqliteCommandReceiptRepository)
        == receipt_methods
    )
    assert _methods(RetentionRepository) == {"purge_batch"}
    assert _methods(SqliteRetentionRepository) == {"purge_batch"}
    assert _methods(TraceEventRepository) == {"append", "list_page", "purge_before"}
    assert _methods(SqliteTraceEventRepository) == {"append", "list_page", "purge_before"}
    assert _methods(AuditEventRepository) == {"append", "list_page", "purge_before"}
    assert _methods(SqliteAuditEventRepository) == {"append", "list_page", "purge_before"}


def test_legacy_repository_paths__symbols_and_dependency__directions_are_absent() -> None:
    old_paths = (
        _SOURCE / "ports" / "persistence" / "action_dependency_repository.py",
        _SOURCE / "ports" / "persistence" / "audit_repository.py",
        _SOURCE / "ports" / "persistence" / "trace_repository.py",
        _SOURCE
        / "adapters"
        / "persistence"
        / "sqlite"
        / "repositories"
        / "action_dependency_repository.py",
        _SOURCE / "adapters" / "persistence" / "sqlite" / "repositories" / "audit_repository.py",
        _SOURCE / "adapters" / "persistence" / "sqlite" / "repositories" / "trace_repository.py",
    )
    assert not any(path.exists() for path in old_paths)

    production = "\n".join(path.read_text(encoding="utf-8") for path in _SOURCE.rglob("*.py"))
    for stale in (
        ".add_received(",
        ".finish_json(",
        ".has_applied_request_cancel(",
        "PurgeObservabilityDataService",
        "SQLiteRunRepository",
        "SQLitePlanRepository",
        "SQLiteActionRepository",
        "SQLiteApprovalRepository",
        "SQLiteExecutionAttemptRepository",
        "SQLiteVerificationRepository",
        "SQLiteEvidenceRepository",
    ):
        assert stale not in production

    application = "\n".join(
        path.read_text(encoding="utf-8") for path in (_SOURCE / "application").rglob("*.py")
    )
    persistence = "\n".join(
        path.read_text(encoding="utf-8")
        for root in (_SOURCE / "ports" / "persistence", _SOURCE / "adapters" / "persistence")
        for path in root.rglob("*.py")
    )
    domain = "\n".join(
        path.read_text(encoding="utf-8") for path in (_SOURCE / "domain").rglob("*.py")
    )
    assert "google_work_agent.adapters.persistence.sqlite" not in application
    assert "google_work_agent.application" not in persistence
    assert "google_work_agent.adapters.persistence" not in domain

    adapter_barrel = (_SOURCE / "adapters" / "persistence" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert "Repository" not in adapter_barrel
