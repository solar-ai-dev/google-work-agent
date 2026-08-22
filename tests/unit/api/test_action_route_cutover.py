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


def test_action_route_has_no_provider_or_persistence_import() -> None:
    source = inspect.getsource(actions)

    assert "google_work_agent.adapters." not in source
    assert "google_work_agent.persistence." not in source
    assert "google_work_agent.adapters.connectors" not in source
