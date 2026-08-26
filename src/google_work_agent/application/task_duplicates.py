"""Application boundary for deterministic Google Task duplicate checks."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol, cast

from google_work_agent.domain.action.model import PolicyViolationError
from google_work_agent.domain.action_risk import normalize_action_risk
from google_work_agent.domain.task_duplicate import (
    DuplicateDecision,
    DuplicateFreshness,
    TaskDuplicateCandidate,
    evaluate_task_duplicate,
    normalize_scheduled_date,
)
from google_work_agent.ports import ResourcePage, ResourceSnapshot, ResourceType

TASK_CREATE_TOOL = "tasks_create_task"
TASK_DUPLICATE_PAGE_SIZE = 100


class TaskListGateway(Protocol):
    def list_tasks(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage: ...


class TaskDuplicateValidator:
    """Read every Tasks page and evaluate only incomplete tasks in one list."""

    def __init__(
        self,
        *,
        gateway: TaskListGateway,
        now_ms: Callable[[], int],
    ) -> None:
        self._gateway = gateway
        self._now_ms = now_ms

    def fresh_risk(self, arguments: Mapping[str, object]) -> dict[str, object]:
        task_list_id, title, scheduled_date = task_create_duplicate_input(arguments)
        candidates: list[TaskDuplicateCandidate] = []
        page_token: str | None = None
        seen_page_tokens: set[str] = set()
        while True:
            page = self._gateway.list_tasks(
                task_list_id=task_list_id,
                page_token=page_token,
                page_size=TASK_DUPLICATE_PAGE_SIZE,
            )
            candidates.extend(
                _candidate_from_snapshot(snapshot, expected_task_list_id=task_list_id)
                for snapshot in page.items
            )
            next_page_token = page.next_page_token
            if next_page_token is None:
                break
            if next_page_token in seen_page_tokens or next_page_token == page_token:
                raise PolicyViolationError("task duplicate pagination token cycle detected")
            seen_page_tokens.add(next_page_token)
            page_token = next_page_token

        result = evaluate_task_duplicate(
            title=title,
            scheduled_date=scheduled_date,
            candidates=tuple(candidates),
        )
        return result.as_risk(
            checked_at_ms=self._now_ms(),
            freshness=DuplicateFreshness.FRESH_GOOGLE_GET,
        )


def evidence_duplicate_risk(
    *,
    arguments: Mapping[str, object],
    acquisition_result: Mapping[str, object],
    checked_at_ms: int,
) -> dict[str, object]:
    """Evaluate only Task resources already acquired by the current Run."""

    task_list_id, title, scheduled_date = task_create_duplicate_input(arguments)
    found_tasks_source = False
    candidates: list[TaskDuplicateCandidate] = []
    summaries = acquisition_result.get("source_summaries")
    if not isinstance(summaries, list):
        return {}
    for summary in summaries:
        if not isinstance(summary, dict) or str(summary.get("source", "")).upper() != "TASKS":
            continue
        found_tasks_source = True
        resources = summary.get("resources")
        if not isinstance(resources, list):
            continue
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            if resource.get("resource_type") != ResourceType.TASK.value:
                continue
            if resource.get("parent_id") != task_list_id:
                continue
            payload = resource.get("payload")
            resource_id = resource.get("resource_id")
            if not isinstance(payload, dict) or not isinstance(resource_id, str):
                continue
            candidate = _candidate_from_values(resource_id=resource_id, payload=payload)
            if candidate is not None:
                candidates.append(candidate)
    if not found_tasks_source:
        return {}
    return evaluate_task_duplicate(
        title=title,
        scheduled_date=scheduled_date,
        candidates=tuple(candidates),
    ).as_risk(
        checked_at_ms=checked_at_ms,
        freshness=DuplicateFreshness.EVIDENCE_ONLY,
    )


def task_create_duplicate_input(
    arguments: Mapping[str, object],
) -> tuple[str, str, str | None]:
    task_list_id = arguments.get("task_list_id")
    payload = arguments.get("payload")
    if not isinstance(task_list_id, str) or not task_list_id.strip():
        raise PolicyViolationError("tasks_create_task requires task_list_id")
    if not isinstance(payload, dict):
        raise PolicyViolationError("tasks_create_task requires payload")
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        raise PolicyViolationError("tasks_create_task requires a non-empty title")
    try:
        scheduled_date = normalize_scheduled_date(payload.get("due"))
    except ValueError as error:
        raise PolicyViolationError(str(error)) from error
    return task_list_id, title, scheduled_date


def merge_duplicate_risk(
    current_risk: Mapping[str, object], duplicate_risk: Mapping[str, object]
) -> dict[str, object]:
    merged = dict(current_risk)
    duplicate = duplicate_risk.get("duplicate")
    if isinstance(duplicate, dict):
        merged["duplicate"] = duplicate
    return normalize_action_risk(merged)


def duplicate_authority(risk: Mapping[str, object]) -> tuple[str, tuple[str, ...]] | None:
    duplicate = risk.get("duplicate")
    if not isinstance(duplicate, dict):
        return None
    decision = duplicate.get("decision")
    matched_ids = duplicate.get("matched_resource_ids")
    if not isinstance(decision, str) or not isinstance(matched_ids, list):
        raise PolicyViolationError("stored task duplicate risk is malformed")
    if decision not in {item.value for item in DuplicateDecision}:
        raise PolicyViolationError("stored task duplicate decision is invalid")
    if any(not isinstance(item, str) for item in matched_ids):
        raise PolicyViolationError("stored task duplicate resource ids are invalid")
    return decision, tuple(sorted(set(cast(list[str], matched_ids))))


def approval_source_snapshot_for_task_duplicate(
    *, risk: Mapping[str, object], acknowledged: bool
) -> dict[str, object]:
    duplicate = risk.get("duplicate")
    return {
        "task_duplicate": {
            "risk": duplicate if isinstance(duplicate, dict) else None,
            "acknowledged": acknowledged,
        }
    }


def approval_duplicate_authority(
    source_snapshot: Mapping[str, object],
) -> tuple[str, tuple[str, ...]] | None:
    task_duplicate = source_snapshot.get("task_duplicate")
    if not isinstance(task_duplicate, dict):
        return None
    risk = task_duplicate.get("risk")
    if not isinstance(risk, dict):
        return None
    return duplicate_authority({"duplicate": risk})


def duplicate_change_requires_reapproval(
    *,
    approved: tuple[str, tuple[str, ...]] | None,
    current: tuple[str, tuple[str, ...]] | None,
) -> bool:
    """A newly observed duplicate or changed match set invalidates approval."""

    if current is None or current[0] == DuplicateDecision.NOT_DUPLICATE.value:
        return False
    return current != approved


def require_duplicate_acknowledgement(
    *, risk: Mapping[str, object], acknowledged: bool
) -> DuplicateDecision | None:
    authority = duplicate_authority(risk)
    if authority is None:
        return None
    decision = DuplicateDecision(authority[0])
    if decision is DuplicateDecision.NOT_DUPLICATE:
        return decision
    if not acknowledged:
        if decision is DuplicateDecision.CLEAR_DUPLICATE:
            raise PolicyViolationError(
                "identical incomplete task exists; explicit duplicate override is required"
            )
        raise PolicyViolationError(
            "similar incomplete task exists; explicit duplicate acknowledgement is required"
        )
    return decision


def _candidate_from_snapshot(
    snapshot: ResourceSnapshot, *, expected_task_list_id: str
) -> TaskDuplicateCandidate:
    if snapshot.resource_type is not ResourceType.TASK:
        raise PolicyViolationError("task duplicate source returned a non-task resource")
    if snapshot.parent_id != expected_task_list_id:
        raise PolicyViolationError("task duplicate source returned a task from another list")
    candidate = _candidate_from_values(
        resource_id=snapshot.resource_id,
        payload=snapshot.payload,
    )
    if candidate is None:
        raise PolicyViolationError("task duplicate source returned a malformed task")
    return candidate


def _candidate_from_values(
    *, resource_id: str, payload: Mapping[str, object]
) -> TaskDuplicateCandidate | None:
    title = payload.get("title")
    status = payload.get("status")
    if not isinstance(title, str) or (status is not None and not isinstance(status, str)):
        return None
    try:
        scheduled_date = normalize_scheduled_date(payload.get("due"))
    except ValueError:
        return None
    return TaskDuplicateCandidate(
        resource_id=resource_id,
        title=title,
        scheduled_date=scheduled_date,
        status=cast(str | None, status),
    )


__all__ = [
    "TASK_CREATE_TOOL",
    "TASK_DUPLICATE_PAGE_SIZE",
    "TaskDuplicateValidator",
    "TaskListGateway",
    "approval_duplicate_authority",
    "approval_source_snapshot_for_task_duplicate",
    "duplicate_authority",
    "duplicate_change_requires_reapproval",
    "evidence_duplicate_risk",
    "merge_duplicate_risk",
    "require_duplicate_acknowledgement",
    "task_create_duplicate_input",
]
