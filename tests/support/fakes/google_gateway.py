"""Fixture-backed Google Workspace gateway test double."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from google_work_agent.ports import (
    FreeBusyCalendar,
    FreeBusyInterval,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    ResourcePage,
    ResourceSnapshot,
    ResourceType,
)
from tests.support.fixtures import ProductFixtureSnapshot


class GoogleGatewayFaultKind(StrEnum):
    """Supported deterministic gateway fault kinds."""

    HTTP_401 = "HTTP_401"
    HTTP_403 = "HTTP_403"
    HTTP_404 = "HTTP_404"
    HTTP_409 = "HTTP_409"
    HTTP_429 = "HTTP_429"
    HTTP_500 = "HTTP_500"
    HTTP_503 = "HTTP_503"
    TIMEOUT_BEFORE_DELIVERY = "TIMEOUT_BEFORE_DELIVERY"
    TIMEOUT_AFTER_DELIVERY = "TIMEOUT_AFTER_DELIVERY"
    RESPONSE_LOST_AFTER_MUTATION = "RESPONSE_LOST_AFTER_MUTATION"
    CONNECTION_CLOSED_BEFORE_DELIVERY = "CONNECTION_CLOSED_BEFORE_DELIVERY"
    CONNECTION_CLOSED_AFTER_DELIVERY = "CONNECTION_CLOSED_AFTER_DELIVERY"
    VERIFICATION_MISMATCH = "VERIFICATION_MISMATCH"
    RESOURCE_VERSION_CHANGED = "RESOURCE_VERSION_CHANGED"
    DUPLICATE_RECOVERY_CANDIDATE = "DUPLICATE_RECOVERY_CANDIDATE"
    NO_RECOVERY_CANDIDATE = "NO_RECOVERY_CANDIDATE"


@dataclass(frozen=True, slots=True)
class GoogleGatewayFault:
    """One queued fault for one gateway operation."""

    kind: GoogleGatewayFaultKind


@dataclass(frozen=True, slots=True)
class GoogleGatewayCallRecord:
    """Recorded gateway invocation metadata."""

    operation: str
    arguments: dict[str, object]
    delivered: bool
    mutated: bool


class FakeGoogleGateway:
    """Fixture-backed Google Workspace gateway with deterministic faults."""

    def __init__(self, snapshot: ProductFixtureSnapshot) -> None:
        self._snapshot_id = snapshot.manifest.snapshot_id
        self._resources: dict[tuple[ResourceType, str], ResourceSnapshot] = {
            (resource.resource_type, resource.resource_id): self._copy_snapshot(resource)
            for resource in snapshot.resources
        }
        self._faults: dict[str, list[GoogleGatewayFault]] = {}
        self.call_log: list[GoogleGatewayCallRecord] = []

    def queue_fault(self, *, operation: str, fault: GoogleGatewayFault) -> None:
        """Queue one deterministic fault for an operation."""

        self._faults.setdefault(operation, []).append(fault)

    def search_gmail_threads(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        operation = "search_gmail_threads"
        self._check_fault(operation=operation, can_mutate=False)
        query_lower = query.lower()
        threads = [
            resource
            for resource in self._sorted_resources(ResourceType.GMAIL_THREAD)
            if query_lower in str(resource.payload.get("subject", "")).lower()
            or any(
                query_lower in str(participant).lower()
                for participant in resource.payload.get("participants", [])
            )
        ]
        return self._paginate(
            operation=operation,
            arguments={"query": query, "page_token": page_token, "page_size": page_size},
            items=threads,
            page_token=page_token,
            page_size=page_size,
        )

    def get_gmail_thread(self, *, thread_id: str) -> ResourceSnapshot:
        return self._read_one("get_gmail_thread", ResourceType.GMAIL_THREAD, thread_id)

    def get_gmail_message(self, *, message_id: str) -> ResourceSnapshot:
        return self._read_one("get_gmail_message", ResourceType.GMAIL_MESSAGE, message_id)

    def create_gmail_draft(
        self,
        *,
        payload: dict[str, object],
        claim_context: dict[str, object] | None = None,
    ) -> ResourceSnapshot:
        del claim_context
        return self._create_one("create_gmail_draft", ResourceType.GMAIL_DRAFT, payload)

    def update_gmail_draft(
        self,
        *,
        draft_id: str,
        payload: dict[str, object],
        claim_context: dict[str, object] | None = None,
    ) -> ResourceSnapshot:
        del claim_context
        return self._update_one("update_gmail_draft", ResourceType.GMAIL_DRAFT, draft_id, payload)

    def get_gmail_draft(self, *, draft_id: str) -> ResourceSnapshot:
        return self._read_one("get_gmail_draft", ResourceType.GMAIL_DRAFT, draft_id)

    def send_gmail(
        self,
        *,
        draft_id: str,
        recovery_fingerprint: str | None,
        claim_context: dict[str, object] | None = None,
    ) -> ResourceSnapshot:
        del claim_context
        draft = self._resources.get((ResourceType.GMAIL_DRAFT, draft_id))
        if draft is None:
            raise LookupError(f"draft not found: {draft_id}")
        payload = deepcopy(draft.payload)
        payload["recovery_fingerprint"] = recovery_fingerprint
        payload["sent"] = True
        payload["draft_id"] = draft_id
        payload["resource_id"] = f"sent-{draft_id}"
        return self._create_one(
            "send_gmail",
            ResourceType.GMAIL_MESSAGE,
            payload,
            parent_id=draft.parent_id,
        )

    def list_task_lists(
        self,
        *,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        operation = "list_task_lists"
        self._check_fault(operation=operation, can_mutate=False)
        return self._paginate(
            operation=operation,
            arguments={"page_token": page_token, "page_size": page_size},
            items=self._sorted_resources(ResourceType.TASK_LIST),
            page_token=page_token,
            page_size=page_size,
        )

    def list_tasks(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        operation = "list_tasks"
        self._check_fault(operation=operation, can_mutate=False)
        tasks = [
            resource
            for resource in self._sorted_resources(ResourceType.TASK)
            if resource.parent_id == task_list_id
        ]
        return self._paginate(
            operation=operation,
            arguments={
                "task_list_id": task_list_id,
                "page_token": page_token,
                "page_size": page_size,
            },
            items=tasks,
            page_token=page_token,
            page_size=page_size,
        )

    def get_task(self, *, task_list_id: str, task_id: str) -> ResourceSnapshot:
        task = self._read_one("get_task", ResourceType.TASK, task_id)
        if task.parent_id != task_list_id:
            raise LookupError(f"task {task_id} does not belong to task list {task_list_id}")
        return task

    def create_task(
        self,
        *,
        task_list_id: str,
        payload: dict[str, object],
        claim_context: dict[str, object] | None = None,
    ) -> ResourceSnapshot:
        del claim_context
        created = self._create_one(
            "create_task", ResourceType.TASK, payload, parent_id=task_list_id
        )
        if created.parent_id != task_list_id:
            raise AssertionError("created task parent mismatch")
        return created

    def update_task(
        self,
        *,
        task_list_id: str,
        task_id: str,
        payload: dict[str, object],
        claim_context: dict[str, object] | None = None,
    ) -> ResourceSnapshot:
        del claim_context
        task = self._update_one("update_task", ResourceType.TASK, task_id, payload)
        if task.parent_id != task_list_id:
            raise LookupError(f"task {task_id} does not belong to task list {task_list_id}")
        return task

    def list_calendars(
        self,
        *,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        operation = "list_calendars"
        self._check_fault(operation=operation, can_mutate=False)
        return self._paginate(
            operation=operation,
            arguments={"page_token": page_token, "page_size": page_size},
            items=self._sorted_resources(ResourceType.CALENDAR),
            page_token=page_token,
            page_size=page_size,
        )

    def list_calendar_events(
        self,
        *,
        calendar_id: str,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        operation = "list_calendar_events"
        self._check_fault(operation=operation, can_mutate=False)
        events = [
            resource
            for resource in self._sorted_resources(ResourceType.CALENDAR_EVENT)
            if resource.parent_id == calendar_id
        ]
        return self._paginate(
            operation=operation,
            arguments={
                "calendar_id": calendar_id,
                "page_token": page_token,
                "page_size": page_size,
            },
            items=events,
            page_token=page_token,
            page_size=page_size,
        )

    def query_freebusy(self, *, calendar_ids: tuple[str, ...]) -> tuple[FreeBusyCalendar, ...]:
        operation = "query_freebusy"
        self._check_fault(operation=operation, can_mutate=False)
        self.call_log.append(
            GoogleGatewayCallRecord(
                operation=operation,
                arguments={"calendar_ids": list(calendar_ids)},
                delivered=True,
                mutated=False,
            )
        )
        results: list[FreeBusyCalendar] = []
        for calendar_id in calendar_ids:
            freebusy = self._resources.get((ResourceType.CALENDAR_FREEBUSY, calendar_id))
            if freebusy is None:
                raise LookupError(f"freebusy calendar not found: {calendar_id}")
            intervals = tuple(
                FreeBusyInterval(
                    start=str(interval["start"]),
                    end=str(interval["end"]),
                    transparency=str(interval["transparency"]),
                )
                for interval in freebusy.payload.get("intervals", [])
            )
            results.append(FreeBusyCalendar(calendar_id=calendar_id, intervals=intervals))
        return tuple(results)

    def get_calendar_event(self, *, calendar_id: str, event_id: str) -> ResourceSnapshot:
        event = self._read_one("get_calendar_event", ResourceType.CALENDAR_EVENT, event_id)
        if event.parent_id != calendar_id:
            raise LookupError(f"event {event_id} does not belong to calendar {calendar_id}")
        return event

    def create_calendar_event(
        self,
        *,
        calendar_id: str,
        payload: dict[str, object],
        claim_context: dict[str, object] | None = None,
    ) -> ResourceSnapshot:
        del claim_context
        created = self._create_one(
            "create_calendar_event",
            ResourceType.CALENDAR_EVENT,
            payload,
            parent_id=calendar_id,
        )
        if created.parent_id != calendar_id:
            raise AssertionError("created event parent mismatch")
        return created

    def update_calendar_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
        payload: dict[str, object],
        claim_context: dict[str, object] | None = None,
    ) -> ResourceSnapshot:
        del claim_context
        event = self._update_one(
            "update_calendar_event", ResourceType.CALENDAR_EVENT, event_id, payload
        )
        if event.parent_id != calendar_id:
            raise LookupError(f"event {event_id} does not belong to calendar {calendar_id}")
        return event

    def delete_calendar_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
        claim_context: dict[str, object] | None = None,
    ) -> ResourceSnapshot:
        del claim_context
        return self._delete_one(
            "delete_calendar_event",
            ResourceType.CALENDAR_EVENT,
            event_id,
            parent_id=calendar_id,
        )

    def search_by_recovery_fingerprint(
        self,
        *,
        resource_type: ResourceType,
        recovery_fingerprint: str,
    ) -> tuple[ResourceSnapshot, ...]:
        operation = "search_by_recovery_fingerprint"
        fault = self._pop_fault(operation)
        if fault is not None:
            if fault.kind is GoogleGatewayFaultKind.DUPLICATE_RECOVERY_CANDIDATE:
                results = tuple(self._sorted_resources(resource_type)[:2])
                self.call_log.append(
                    GoogleGatewayCallRecord(
                        operation=operation,
                        arguments={
                            "resource_type": resource_type.value,
                            "recovery_fingerprint": recovery_fingerprint,
                        },
                        delivered=True,
                        mutated=False,
                    )
                )
                return tuple(self._copy_snapshot(item) for item in results)
            if fault.kind is GoogleGatewayFaultKind.NO_RECOVERY_CANDIDATE:
                self.call_log.append(
                    GoogleGatewayCallRecord(
                        operation=operation,
                        arguments={
                            "resource_type": resource_type.value,
                            "recovery_fingerprint": recovery_fingerprint,
                        },
                        delivered=True,
                        mutated=False,
                    )
                )
                return ()
            self._raise_fault(fault=fault, delivered=True, mutated=False)

        results = tuple(
            self._copy_snapshot(resource)
            for resource in self._sorted_resources(resource_type)
            if resource.recovery_fingerprint == recovery_fingerprint
        )
        self.call_log.append(
            GoogleGatewayCallRecord(
                operation=operation,
                arguments={
                    "resource_type": resource_type.value,
                    "recovery_fingerprint": recovery_fingerprint,
                },
                delivered=True,
                mutated=False,
            )
        )
        return results

    def count_calls(self, operation: str) -> int:
        """Return how many times an operation was invoked."""

        return sum(1 for record in self.call_log if record.operation == operation)

    def _read_one(
        self, operation: str, resource_type: ResourceType, resource_id: str
    ) -> ResourceSnapshot:
        fault = self._pop_fault(operation)
        resource = self._resources.get((resource_type, resource_id))
        if resource is None:
            raise LookupError(f"resource not found: {resource_type.value}/{resource_id}")
        if fault is not None:
            if fault.kind is GoogleGatewayFaultKind.RESOURCE_VERSION_CHANGED:
                updated = self._increment_version(resource)
                self._resources[(resource_type, resource_id)] = updated
                resource = updated
            elif fault.kind is GoogleGatewayFaultKind.VERIFICATION_MISMATCH:
                mismatched = self._copy_snapshot(resource)
                mismatched.payload["verification_marker"] = "mismatch"
                self.call_log.append(
                    GoogleGatewayCallRecord(
                        operation=operation,
                        arguments={"resource_id": resource_id},
                        delivered=True,
                        mutated=False,
                    )
                )
                return mismatched
            else:
                self._raise_fault(fault=fault, delivered=False, mutated=False)
        self.call_log.append(
            GoogleGatewayCallRecord(
                operation=operation,
                arguments={"resource_id": resource_id},
                delivered=True,
                mutated=False,
            )
        )
        return self._copy_snapshot(resource)

    def _create_one(
        self,
        operation: str,
        resource_type: ResourceType,
        payload: dict[str, object],
        *,
        parent_id: str | None = None,
    ) -> ResourceSnapshot:
        fault = self._pop_fault(operation)
        if fault is not None and fault.kind in {
            GoogleGatewayFaultKind.TIMEOUT_BEFORE_DELIVERY,
            GoogleGatewayFaultKind.CONNECTION_CLOSED_BEFORE_DELIVERY,
            GoogleGatewayFaultKind.HTTP_401,
            GoogleGatewayFaultKind.HTTP_403,
            GoogleGatewayFaultKind.HTTP_404,
            GoogleGatewayFaultKind.HTTP_409,
            GoogleGatewayFaultKind.HTTP_429,
        }:
            self._raise_fault(fault=fault, delivered=False, mutated=False)

        resource_id = str(
            payload.get("resource_id") or f"{resource_type.value}-{len(self._resources) + 1}"
        )
        related_resource_ids = cast(
            list[object] | tuple[object, ...],
            payload.get("related_resource_ids", ()),
        )
        snapshot = ResourceSnapshot(
            fixture_snapshot_id=self._snapshot_id,
            resource_type=resource_type,
            resource_id=resource_id,
            parent_id=parent_id,
            related_resource_ids=tuple(sorted(str(value) for value in related_resource_ids)),
            version="1",
            recovery_fingerprint=str(payload.get("recovery_fingerprint"))
            if "recovery_fingerprint" in payload
            else None,
            payload=deepcopy(payload),
        )
        self._resources[(resource_type, resource_id)] = snapshot
        self.call_log.append(
            GoogleGatewayCallRecord(
                operation=operation,
                arguments={"payload": deepcopy(payload), "parent_id": parent_id},
                delivered=True,
                mutated=True,
            )
        )
        if fault is not None:
            self._raise_fault(fault=fault, delivered=True, mutated=True)
        return self._copy_snapshot(snapshot)

    def _update_one(
        self,
        operation: str,
        resource_type: ResourceType,
        resource_id: str,
        payload: dict[str, object],
    ) -> ResourceSnapshot:
        fault = self._pop_fault(operation)
        resource = self._resources.get((resource_type, resource_id))
        if resource is None:
            raise LookupError(f"resource not found: {resource_type.value}/{resource_id}")
        if fault is not None and fault.kind in {
            GoogleGatewayFaultKind.TIMEOUT_BEFORE_DELIVERY,
            GoogleGatewayFaultKind.CONNECTION_CLOSED_BEFORE_DELIVERY,
            GoogleGatewayFaultKind.HTTP_401,
            GoogleGatewayFaultKind.HTTP_403,
            GoogleGatewayFaultKind.HTTP_404,
            GoogleGatewayFaultKind.HTTP_409,
            GoogleGatewayFaultKind.HTTP_429,
        }:
            self._raise_fault(fault=fault, delivered=False, mutated=False)

        merged_payload = deepcopy(resource.payload)
        merged_payload.update(deepcopy(payload))
        updated = ResourceSnapshot(
            fixture_snapshot_id=resource.fixture_snapshot_id,
            resource_type=resource.resource_type,
            resource_id=resource.resource_id,
            parent_id=resource.parent_id,
            related_resource_ids=resource.related_resource_ids,
            version=str(int(resource.version) + 1),
            recovery_fingerprint=resource.recovery_fingerprint,
            payload=merged_payload,
        )
        self._resources[(resource_type, resource_id)] = updated
        self.call_log.append(
            GoogleGatewayCallRecord(
                operation=operation,
                arguments={"resource_id": resource_id, "payload": deepcopy(payload)},
                delivered=True,
                mutated=True,
            )
        )
        if fault is not None:
            self._raise_fault(fault=fault, delivered=True, mutated=True)
        return self._copy_snapshot(updated)

    def _delete_one(
        self,
        operation: str,
        resource_type: ResourceType,
        resource_id: str,
        *,
        parent_id: str,
    ) -> ResourceSnapshot:
        fault = self._pop_fault(operation)
        resource = self._resources.get((resource_type, resource_id))
        if resource is None:
            raise LookupError(f"resource not found: {resource_type.value}/{resource_id}")
        if resource.parent_id != parent_id:
            raise LookupError(f"resource {resource_id} does not belong to {parent_id}")
        if fault is not None and fault.kind in {
            GoogleGatewayFaultKind.TIMEOUT_BEFORE_DELIVERY,
            GoogleGatewayFaultKind.CONNECTION_CLOSED_BEFORE_DELIVERY,
            GoogleGatewayFaultKind.HTTP_401,
            GoogleGatewayFaultKind.HTTP_403,
            GoogleGatewayFaultKind.HTTP_404,
            GoogleGatewayFaultKind.HTTP_409,
            GoogleGatewayFaultKind.HTTP_429,
        }:
            self._raise_fault(fault=fault, delivered=False, mutated=False)

        del self._resources[(resource_type, resource_id)]
        self.call_log.append(
            GoogleGatewayCallRecord(
                operation=operation,
                arguments={"resource_id": resource_id, "parent_id": parent_id},
                delivered=True,
                mutated=True,
            )
        )
        if fault is not None:
            self._raise_fault(fault=fault, delivered=True, mutated=True)
        return ResourceSnapshot(
            fixture_snapshot_id=resource.fixture_snapshot_id,
            resource_type=resource.resource_type,
            resource_id=resource.resource_id,
            parent_id=resource.parent_id,
            related_resource_ids=resource.related_resource_ids,
            version=resource.version,
            recovery_fingerprint=resource.recovery_fingerprint,
            payload={"deleted": True},
        )

    def _paginate(
        self,
        *,
        operation: str,
        arguments: dict[str, object],
        items: list[ResourceSnapshot],
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        start = int(page_token) if page_token is not None else 0
        window = items[start : start + page_size]
        next_token = None if start + page_size >= len(items) else str(start + page_size)
        self.call_log.append(
            GoogleGatewayCallRecord(
                operation=operation,
                arguments=deepcopy(arguments),
                delivered=True,
                mutated=False,
            )
        )
        return ResourcePage(
            items=tuple(self._copy_snapshot(item) for item in window),
            next_page_token=next_token,
        )

    def _sorted_resources(self, resource_type: ResourceType) -> list[ResourceSnapshot]:
        return sorted(
            (
                resource
                for resource in self._resources.values()
                if resource.resource_type is resource_type
            ),
            key=lambda resource: (resource.parent_id or "", resource.resource_id),
        )

    def _check_fault(self, *, operation: str, can_mutate: bool) -> None:
        fault = self._pop_fault(operation)
        if fault is None:
            return
        self._raise_fault(fault=fault, delivered=not can_mutate, mutated=False)

    def _pop_fault(self, operation: str) -> GoogleGatewayFault | None:
        queue = self._faults.get(operation)
        if not queue:
            return None
        return queue.pop(0)

    def _raise_fault(
        self,
        *,
        fault: GoogleGatewayFault,
        delivered: bool,
        mutated: bool,
    ) -> None:
        code_map = {
            GoogleGatewayFaultKind.HTTP_401: GoogleWorkspaceErrorCode.AUTH_EXPIRED,
            GoogleGatewayFaultKind.HTTP_403: GoogleWorkspaceErrorCode.PERMISSION_DENIED,
            GoogleGatewayFaultKind.HTTP_404: GoogleWorkspaceErrorCode.NOT_FOUND,
            GoogleGatewayFaultKind.HTTP_409: GoogleWorkspaceErrorCode.CONFLICT,
            GoogleGatewayFaultKind.HTTP_429: GoogleWorkspaceErrorCode.RATE_LIMITED,
            GoogleGatewayFaultKind.HTTP_500: GoogleWorkspaceErrorCode.UPSTREAM_5XX,
            GoogleGatewayFaultKind.HTTP_503: GoogleWorkspaceErrorCode.UPSTREAM_5XX,
            GoogleGatewayFaultKind.TIMEOUT_BEFORE_DELIVERY: GoogleWorkspaceErrorCode.TIMEOUT,
            GoogleGatewayFaultKind.TIMEOUT_AFTER_DELIVERY: GoogleWorkspaceErrorCode.TIMEOUT,
            GoogleGatewayFaultKind.RESPONSE_LOST_AFTER_MUTATION: (GoogleWorkspaceErrorCode.TIMEOUT),
            GoogleGatewayFaultKind.CONNECTION_CLOSED_BEFORE_DELIVERY: (
                GoogleWorkspaceErrorCode.CONNECTION_CLOSED
            ),
            GoogleGatewayFaultKind.CONNECTION_CLOSED_AFTER_DELIVERY: (
                GoogleWorkspaceErrorCode.CONNECTION_CLOSED
            ),
            GoogleGatewayFaultKind.VERIFICATION_MISMATCH: (
                GoogleWorkspaceErrorCode.VERIFICATION_MISMATCH
            ),
            GoogleGatewayFaultKind.RESOURCE_VERSION_CHANGED: (
                GoogleWorkspaceErrorCode.RESOURCE_VERSION_CHANGED
            ),
            GoogleGatewayFaultKind.DUPLICATE_RECOVERY_CANDIDATE: (
                GoogleWorkspaceErrorCode.DUPLICATE_RECOVERY_CANDIDATE
            ),
            GoogleGatewayFaultKind.NO_RECOVERY_CANDIDATE: (
                GoogleWorkspaceErrorCode.NO_RECOVERY_CANDIDATE
            ),
        }
        raise GoogleWorkspaceGatewayError(
            code=code_map[fault.kind],
            message=f"fake gateway fault: {fault.kind.value}",
            delivered=delivered,
            mutated=mutated,
        )

    def _increment_version(self, resource: ResourceSnapshot) -> ResourceSnapshot:
        return ResourceSnapshot(
            fixture_snapshot_id=resource.fixture_snapshot_id,
            resource_type=resource.resource_type,
            resource_id=resource.resource_id,
            parent_id=resource.parent_id,
            related_resource_ids=resource.related_resource_ids,
            version=str(int(resource.version) + 1),
            recovery_fingerprint=resource.recovery_fingerprint,
            payload=deepcopy(resource.payload),
        )

    def _copy_snapshot(self, snapshot: ResourceSnapshot) -> ResourceSnapshot:
        return ResourceSnapshot(
            fixture_snapshot_id=snapshot.fixture_snapshot_id,
            resource_type=snapshot.resource_type,
            resource_id=snapshot.resource_id,
            parent_id=snapshot.parent_id,
            related_resource_ids=tuple(snapshot.related_resource_ids),
            version=snapshot.version,
            recovery_fingerprint=snapshot.recovery_fingerprint,
            payload=deepcopy(snapshot.payload),
        )
