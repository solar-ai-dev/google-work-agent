from __future__ import annotations

import inspect

from google_work_agent.application.use_cases.action import (
    approve_action,
    modify_action,
    prepare_write_retry,
    reject_action,
)


def test_canonical_handlers_do_not_delegate_to_legacy_semantic_services() -> None:
    sources = {
        "approve": inspect.getsource(approve_action),
        "modify": inspect.getsource(modify_action),
        "reject": inspect.getsource(reject_action),
        "retry": inspect.getsource(prepare_write_retry),
    }

    assert "ApproveWriteActionService" not in sources["approve"]
    assert "approve_service" not in sources["approve"]
    assert "ModifyWriteActionService" not in sources["modify"]
    assert "modify_service" not in sources["modify"]
    assert "RejectWriteActionService" not in sources["reject"]
    assert "reject_service" not in sources["reject"]
    assert "PrepareWriteRetryService" not in sources["retry"]
    assert "prepare_retry_service" not in sources["retry"]


def test_canonical_handlers_own_persistence_boundaries() -> None:
    assert "command_receipts" in inspect.getsource(approve_action)
    assert "transition_approve_action" in inspect.getsource(approve_action)
    assert "unit_of_work.actions.update_if_version_and_status" in inspect.getsource(approve_action)
    assert "command_receipts" in inspect.getsource(modify_action)
    assert "transition_modify_action" in inspect.getsource(modify_action)
    assert "unit_of_work.actions.update_if_version_and_status" in inspect.getsource(modify_action)
    assert "command_receipts" in inspect.getsource(reject_action)
    assert "transition_reject_action" in inspect.getsource(reject_action)
    assert "unit_of_work.actions.update_if_version_and_status" in inspect.getsource(reject_action)
    assert "command_receipts" in inspect.getsource(prepare_write_retry)
    assert "transition_prepare_write_retry" in inspect.getsource(prepare_write_retry)
    assert "unit_of_work.actions.update_if_version_and_status" in inspect.getsource(
        prepare_write_retry
    )


def test_approve_source_authority_is_server_side_persisted_resource_ref_chain() -> None:
    source = inspect.getsource(approve_action)
    assert "action.target_resource_ref_id" in source
    assert "unit_of_work.resource_refs.get" in source
    assert "build_approval_source_snapshot" in source
    assert "source_snapshot_hash" in source
    assert "calculate_recovery_fingerprint" in source
