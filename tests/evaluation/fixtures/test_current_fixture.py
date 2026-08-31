from __future__ import annotations

import json

import pytest
from evaluation.datasets.load_canonical_cases import load_canonical_cases
from evaluation.fixtures.fixture_environment import FixtureEffectError, FixtureEnvironment
from evaluation.fixtures.load_current_fixture import load_current_fixture
from evaluation.fixtures.product_resource_projection import project_product_resources

from google_work_agent.ports.connector.contracts.google_workspace import ResourceType


def test_every_current_case_resource_exists_in_its_executable_fixture() -> None:
    cases = load_canonical_cases()
    fixture_hashes: dict[str, str] = {}
    for case in cases:
        fixture = load_current_fixture(case.fixture_snapshot_id)
        serialized = json.dumps(fixture.model_dump(mode="json"), ensure_ascii=False)
        assert all(resource_id in serialized for resource_id in case.required_resource_ids)
        assert case.scenario_family_id in fixture.scenario_family_ids
        assert fixture.fixture_relation_family == case.fixture_relation_family
        fixture_hashes.setdefault(case.fixture_snapshot_id, fixture.stable_hash())
        assert fixture_hashes[case.fixture_snapshot_id] == fixture.stable_hash()


def test_fixture_reset_and_durable_effect_replay_are_isolated() -> None:
    fixture = load_current_fixture("FX-009-A9C7")
    first = FixtureEnvironment(fixture)
    second = FixtureEnvironment(fixture)
    before = first.snapshot()
    tasks = before["tasks"]
    assert isinstance(tasks, dict)
    original = next(row for row in tasks["tasks"] if row["task_id"] == "HX9-TASK-NOTIFY")
    updated = {**original, "due": "2026-09-08T18:00:00+09:00"}
    after = first.replay(
        [
            {
                "operation": "UPDATE",
                "collection": "tasks.tasks",
                "resource_id": "HX9-TASK-NOTIFY",
                "after": updated,
            }
        ]
    )
    assert after != before
    assert second.snapshot() == before


def test_fixture_replay_rejects_unbounded_or_impossible_effect() -> None:
    environment = FixtureEnvironment(load_current_fixture("FX-009-A9C7"))
    with pytest.raises(FixtureEffectError):
        environment.replay(
            [
                {
                    "operation": "DELETE",
                    "collection": "tasks.tasks",
                    "resource_id": "missing",
                }
            ]
        )


def test_current_fixture_projects_to_exact_product_connector_resources() -> None:
    fixture = load_current_fixture("FW-D-002")
    resources = project_product_resources(fixture)
    by_identity = {(item.resource_type, item.resource_id): item for item in resources}

    thread = by_identity[(ResourceType.GMAIL_THREAD, "GTH-B-001")]
    latest = by_identity[(ResourceType.GMAIL_MESSAGE, "GM-B-002")]
    assert thread.payload["message_ids"] == ["GM-B-001", "GM-B-002"]
    assert latest.parent_id == "GTH-B-001"
    assert "최종 서명 기한은 8월 16일 18시" in str(latest.payload["body"])
    assert (ResourceType.TASK_LIST, "TL-WORK") in by_identity
    assert (ResourceType.CALENDAR, "CAL-PRIMARY") in by_identity
