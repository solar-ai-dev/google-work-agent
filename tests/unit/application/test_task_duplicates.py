"""FN-031 source, pagination, and freshness tests."""

from collections.abc import Mapping

import pytest

from google_work_agent.application.task_duplicates import (
    TASK_DUPLICATE_PAGE_SIZE,
    TaskDuplicateValidator,
    evidence_duplicate_risk,
)
from google_work_agent.domain.action.model import PolicyViolationError
from google_work_agent.ports import (
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    ResourcePage,
    ResourceSnapshot,
    ResourceType,
)


def _task(
    resource_id: str,
    *,
    title: str = "Send summary",
    due: str | None = None,
    status: str = "needsAction",
    parent_id: str = "list-1",
) -> ResourceSnapshot:
    payload: dict[str, object] = {"title": title, "status": status}
    if due is not None:
        payload["due"] = due
    return ResourceSnapshot(
        fixture_snapshot_id=resource_id,
        resource_type=ResourceType.TASK,
        resource_id=resource_id,
        parent_id=parent_id,
        related_resource_ids=(parent_id,),
        version="1",
        recovery_fingerprint=None,
        payload=payload,
    )


class _PagedGateway:
    def __init__(self, pages: Mapping[str | None, ResourcePage]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, str | None, int]] = []

    def list_tasks(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        self.calls.append((task_list_id, page_token, page_size))
        return self.pages[page_token]


def _arguments(*, due: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"title": "Send summary"}
    if due is not None:
        payload["due"] = due
    return {"task_list_id": "list-1", "payload": payload}


def test_fresh_check_reads_every_page_and_finds_later_duplicate() -> None:
    gateway = _PagedGateway(
        {
            None: ResourcePage(items=(_task("other", title="Other"),), next_page_token="p2"),
            "p2": ResourcePage(items=(_task("duplicate"),), next_page_token=None),
        }
    )

    risk = TaskDuplicateValidator(gateway=gateway, now_ms=lambda: 123).fresh_risk(_arguments())

    assert risk["duplicate"]["decision"] == "CLEAR_DUPLICATE"  # type: ignore[index]
    assert gateway.calls == [
        ("list-1", None, TASK_DUPLICATE_PAGE_SIZE),
        ("list-1", "p2", TASK_DUPLICATE_PAGE_SIZE),
    ]


def test_completed_task_is_excluded_from_fresh_check() -> None:
    gateway = _PagedGateway(
        {None: ResourcePage(items=(_task("done", status="completed"),), next_page_token=None)}
    )

    risk = TaskDuplicateValidator(gateway=gateway, now_ms=lambda: 123).fresh_risk(_arguments())

    assert risk["duplicate"]["decision"] == "NOT_DUPLICATE"  # type: ignore[index]


def test_fresh_check_has_no_date_window() -> None:
    gateway = _PagedGateway(
        {
            None: ResourcePage(
                items=(_task("old", due="2001-01-01T00:00:00.000Z"),),
                next_page_token=None,
            )
        }
    )

    risk = TaskDuplicateValidator(gateway=gateway, now_ms=lambda: 123).fresh_risk(
        _arguments(due="2001-01-01T23:59:59Z")
    )

    assert risk["duplicate"]["decision"] == "CLEAR_DUPLICATE"  # type: ignore[index]


def test_fresh_check_detects_page_token_cycle() -> None:
    gateway = _PagedGateway(
        {
            None: ResourcePage(items=(), next_page_token="p2"),
            "p2": ResourcePage(items=(), next_page_token="p2"),
        }
    )

    with pytest.raises(PolicyViolationError, match="token cycle"):
        TaskDuplicateValidator(gateway=gateway, now_ms=lambda: 123).fresh_risk(_arguments())


@pytest.mark.parametrize(
    "source_error",
    [
        GoogleWorkspaceGatewayError(
            code=GoogleWorkspaceErrorCode.RATE_LIMITED,
            message="rate limited",
            delivered=False,
            mutated=False,
        ),
        GoogleWorkspaceGatewayError(
            code=GoogleWorkspaceErrorCode.UPSTREAM_5XX,
            message="upstream failed",
            delivered=False,
            mutated=False,
        ),
        GoogleWorkspaceGatewayError(
            code=GoogleWorkspaceErrorCode.TIMEOUT,
            message="timed out",
            delivered=False,
            mutated=False,
        ),
        TimeoutError("source unavailable"),
    ],
)
def test_fresh_check_propagates_source_failure(source_error: Exception) -> None:
    class _FailingGateway:
        def list_tasks(self, **_: object) -> ResourcePage:
            raise source_error

    with pytest.raises(type(source_error)):
        TaskDuplicateValidator(gateway=_FailingGateway(), now_ms=lambda: 123).fresh_risk(
            _arguments()
        )


def test_evidence_check_does_not_invent_a_result_without_tasks_source() -> None:
    assert (
        evidence_duplicate_risk(
            arguments=_arguments(),
            acquisition_result={"source_summaries": []},
            checked_at_ms=123,
        )
        == {}
    )


def test_evidence_check_uses_only_same_list_current_run_resources() -> None:
    resource = {
        "resource_type": "task",
        "resource_id": "other-list-task",
        "parent_id": "list-2",
        "payload": {"title": "Send summary", "status": "needsAction"},
    }

    risk = evidence_duplicate_risk(
        arguments=_arguments(),
        acquisition_result={"source_summaries": [{"source": "TASKS", "resources": [resource]}]},
        checked_at_ms=123,
    )

    assert risk["duplicate"]["decision"] == "NOT_DUPLICATE"  # type: ignore[index]
    assert risk["duplicate"]["freshness"] == "EVIDENCE_ONLY"  # type: ignore[index]
