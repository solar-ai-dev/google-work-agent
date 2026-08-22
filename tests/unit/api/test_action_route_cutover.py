from __future__ import annotations

import inspect

from google_work_agent.api.routes import actions


def test_action_route_has_zero_uow_or_repository_traversal() -> None:
    source = inspect.getsource(actions)

    assert "with dependencies.unit_of_work_factory()" not in source
    assert ".actions.get_by_id(" not in source
    assert ".plans.get_by_id(" not in source
    assert ".runs.get_by_id(" not in source
    assert ".conversations.get_by_id(" not in source


def test_action_route_binds_only_canonical_action_use_cases() -> None:
    source = inspect.getsource(actions)

    assert "application.use_cases.action.approve_action" in source
    assert "application.use_cases.action.modify_action" in source
    assert "application.use_cases.action.reject_action" in source
    assert "application.use_cases.action.prepare_write_retry" in source
    assert "application.write_actions import" not in source
    assert "application.start_run import" not in source
    assert "application.projections import" not in source


def test_action_route_does_not_invoke_legacy_semantics_for_approve_reject_retry() -> None:
    source = inspect.getsource(actions)

    assert "approve_action_service()" not in source
    assert "reject_action_service()" not in source
    assert "prepare_retry_service()" not in source
    assert "ApproveWriteAction" not in source
    assert "RejectWriteAction" not in source
    assert "PrepareWriteRetryService" not in source


def test_modify_legacy_surface_is_wiring_only_gateway_bridge() -> None:
    source = inspect.getsource(actions)

    assert "legacy_surface = dependencies.modify_action_service()" in source
    assert "legacy_surface(" not in source
    assert "gateway=_modify_gateway(dependencies)" in source
    assert "ModifyActionHandler(" in source


def test_action_route_has_no_provider_or_persistence_import() -> None:
    source = inspect.getsource(actions)

    assert "google_work_agent.adapters." not in source
    assert "google_work_agent.persistence." not in source
    assert "google_work_agent.adapters.connectors" not in source
