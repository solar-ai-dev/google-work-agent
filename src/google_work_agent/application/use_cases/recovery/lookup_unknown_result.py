"""Look up an uncertain external result without issuing a Write."""

from collections.abc import Callable
from dataclasses import dataclass
from json import loads
from typing import Literal, cast

from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.verification.verify_effect import (
    SelectedResourceRefV1,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadPort, JsonValue
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class LookupUnknownResultQueryV1:
    run_id: str
    action_id: str
    execution_attempt_id: str
    effect: Literal["CREATE", "UPDATE", "DELETE", "SEND"]
    recovery_fingerprint: str
    target_resource_ref: SelectedResourceRefV1 | None


@dataclass(frozen=True, slots=True)
class UnknownResultLookupResultV1:
    disposition: Literal["MUTATION_FOUND", "MUTATION_NOT_FOUND", "UNRESOLVED"]
    strategy: Literal["RESOURCE_SEARCH", "GET_TARGET", "MESSAGE_SEARCH"]
    candidate_resource_refs: list[str]
    evidence_refs: list[str]
    reason_codes: list[str]


@dataclass(frozen=True, slots=True)
class PersistedUnknownLookupInput:
    query: LookupUnknownResultQueryV1
    tool_name: str
    arguments: dict[str, object]


class LookupUnknownResultHandler:
    def __init__(
        self,
        *,
        connector_read: ConnectorReadPort,
        tool_registry: SignedToolRegistry,
        connector_id: str = "google_workspace",
        unit_of_work_factory: Callable[[], UnitOfWork] | None = None,
    ) -> None:
        self._connector_read = connector_read
        self._tool_registry = tool_registry
        self._connector_id = connector_id
        self._unit_of_work_factory = unit_of_work_factory

    def project_persisted_query(
        self,
        *,
        run_id: str,
        action_id: str,
        execution_attempt_id: str,
        effect: Literal["CREATE", "UPDATE", "DELETE", "SEND"],
    ) -> PersistedUnknownLookupInput:
        if self._unit_of_work_factory is None:
            raise RuntimeError("persisted unknown-result projection is not configured")
        with self._unit_of_work_factory() as unit_of_work:
            action = unit_of_work.actions.get(action_id)
            attempt = unit_of_work.execution_attempts.get(execution_attempt_id)
            if action is None or attempt is None:
                raise LookupError("unknown-result Action/Attempt binding is missing")
            approval = unit_of_work.approvals.get(attempt.approval_id)
            resource_ref = (
                None
                if action.target_resource_ref_id is None
                else unit_of_work.resource_refs.get(action.target_resource_ref_id)
            )
        if approval is None:
            raise LookupError("unknown-result Approval binding is missing")
        arguments = cast(dict[str, object], loads(action.arguments_json))
        target = (
            _create_recovery_search_scope(action.tool_name, arguments)
            if resource_ref is None
            else SelectedResourceRefV1(
                schema_version=1,
                resource_ref_id=resource_ref.id,
                connector_id=resource_ref.connector_id,
                resource_type=resource_ref.resource_type,
                resource_id=resource_ref.resource_id,
                parent_resource_id=resource_ref.parent_resource_id,
            )
        )
        return PersistedUnknownLookupInput(
            query=LookupUnknownResultQueryV1(
                run_id=run_id,
                action_id=action_id,
                execution_attempt_id=execution_attempt_id,
                effect=effect,
                recovery_fingerprint=approval.recovery_fingerprint,
                target_resource_ref=target,
            ),
            tool_name=action.tool_name,
            arguments=arguments,
        )

    def __call__(self, query: LookupUnknownResultQueryV1) -> UnknownResultLookupResultV1:
        strategy, tool_id, arguments = self._request(query)
        try:
            result = self._connector_read.execute_read(
                self._tool_registry.bind_required(self._connector_id, tool_id, "READ"),
                arguments,
            )
        except ConnectorOperationFailure as error:
            if error.code is ConnectorFailureCode.NOT_FOUND and strategy == "GET_TARGET":
                if query.effect == "DELETE" and query.target_resource_ref is not None:
                    return UnknownResultLookupResultV1(
                        "MUTATION_FOUND",
                        strategy,
                        [query.target_resource_ref.resource_id],
                        [],
                        ["TARGET_ABSENT"],
                    )
                return UnknownResultLookupResultV1(
                    "MUTATION_NOT_FOUND",
                    strategy,
                    [],
                    [],
                    ["TARGET_NOT_FOUND"],
                )
            raise
        if strategy == "GET_TARGET" and query.effect == "DELETE":
            return UnknownResultLookupResultV1(
                "MUTATION_NOT_FOUND",
                strategy,
                [],
                [result.request_id],
                ["TARGET_STILL_PRESENT"],
            )
        candidates = self._candidate_ids(
            result.output,
            recovery_fingerprint=(
                query.recovery_fingerprint if strategy == "RESOURCE_SEARCH" else None
            ),
        )
        if strategy == "GET_TARGET" and query.effect == "UPDATE":
            item = result.output.get("item", result.output)
            if not isinstance(item, dict) or not _contains_fingerprint(
                item, query.recovery_fingerprint
            ):
                return UnknownResultLookupResultV1(
                    "UNRESOLVED",
                    strategy,
                    candidates,
                    [result.request_id],
                    ["TARGET_EXISTS_WITHOUT_MUTATION_PROOF"],
                )
        if len(candidates) == 1:
            disposition: Literal["MUTATION_FOUND", "MUTATION_NOT_FOUND", "UNRESOLVED"] = (
                "MUTATION_FOUND"
            )
            reason_codes = ["SINGLE_MATCH"]
        elif not candidates:
            disposition = "MUTATION_NOT_FOUND"
            reason_codes = ["NO_MATCH"]
        else:
            disposition = "UNRESOLVED"
            reason_codes = ["AMBIGUOUS_MATCHES"]
        return UnknownResultLookupResultV1(
            disposition,
            strategy,
            candidates,
            [result.request_id],
            reason_codes,
        )

    @staticmethod
    def _request(
        query: LookupUnknownResultQueryV1,
    ) -> tuple[
        Literal["RESOURCE_SEARCH", "GET_TARGET", "MESSAGE_SEARCH"],
        str,
        dict[str, JsonValue],
    ]:
        if not query.recovery_fingerprint:
            raise ValueError("recovery_fingerprint is required")
        if query.effect == "SEND":
            return "MESSAGE_SEARCH", "gmail_search_threads", {"query": query.recovery_fingerprint}
        target = query.target_resource_ref
        if query.effect in {"UPDATE", "DELETE"}:
            if target is None:
                raise ValueError("targeted recovery requires a resource reference")
            resource_type = target.resource_type.upper()
            if resource_type == "TASK" and target.parent_resource_id is not None:
                return (
                    "GET_TARGET",
                    "tasks_get_task",
                    {
                        "task_list_id": target.parent_resource_id,
                        "task_id": target.resource_id,
                    },
                )
            if resource_type in {"CALENDAR", "CALENDAR_EVENT"} and (
                target.parent_resource_id is not None
            ):
                return (
                    "GET_TARGET",
                    "calendar_get_event",
                    {
                        "calendar_id": target.parent_resource_id,
                        "event_id": target.resource_id,
                    },
                )
            if resource_type == "GMAIL_DRAFT":
                return "GET_TARGET", "gmail_get_draft", {"draft_id": target.resource_id}
            raise ValueError("unsupported targeted recovery resource")
        resource_type = "" if target is None else target.resource_type.upper()
        if resource_type == "TASK" and target is not None and target.parent_resource_id:
            return (
                "RESOURCE_SEARCH",
                "tasks_list_tasks",
                {
                    "task_list_id": target.parent_resource_id,
                    "query": query.recovery_fingerprint,
                },
            )
        if resource_type in {"CALENDAR", "CALENDAR_EVENT"} and (
            target is not None and target.parent_resource_id
        ):
            return (
                "RESOURCE_SEARCH",
                "calendar_list_events",
                {
                    "calendar_id": target.parent_resource_id,
                    "query": query.recovery_fingerprint,
                },
            )
        return "RESOURCE_SEARCH", "gmail_search_threads", {"query": query.recovery_fingerprint}

    @staticmethod
    def _candidate_ids(
        output: dict[str, JsonValue], *, recovery_fingerprint: str | None = None
    ) -> list[str]:
        raw = output.get("items", output.get("candidates", output.get("item", [])))
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            return []
        candidates: list[str] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            if recovery_fingerprint is not None and not _contains_fingerprint(
                item, recovery_fingerprint
            ):
                continue
            value = item.get("resource_ref_id", item.get("resource_id", item.get("id")))
            if isinstance(value, str) and value:
                candidates.append(value)
        return candidates


def _contains_fingerprint(value: object, fingerprint: str) -> bool:
    if isinstance(value, str):
        return fingerprint in value
    if isinstance(value, list):
        return any(_contains_fingerprint(item, fingerprint) for item in value)
    if isinstance(value, dict):
        return any(_contains_fingerprint(item, fingerprint) for item in value.values())
    return False


def _create_recovery_search_scope(
    tool_name: str, arguments: dict[str, object]
) -> SelectedResourceRefV1 | None:
    if tool_name == "tasks_create_task":
        parent_id = arguments.get("task_list_id")
        resource_type = "task"
    elif tool_name == "calendar_create_event":
        parent_id = arguments.get("calendar_id")
        resource_type = "calendar_event"
    else:
        return None
    if not isinstance(parent_id, str) or not parent_id:
        raise ValueError("create recovery requires a container identity")
    return SelectedResourceRefV1(
        schema_version=1,
        resource_ref_id="recovery-search-scope",
        connector_id="google_workspace",
        resource_type=resource_type,
        resource_id="recovery-search-scope",
        parent_resource_id=parent_id,
    )


__all__ = [
    "LookupUnknownResultHandler",
    "LookupUnknownResultQueryV1",
    "PersistedUnknownLookupInput",
    "UnknownResultLookupResultV1",
]
