"""Read and compare one external effect without lifecycle mutation."""

from collections.abc import Callable
from dataclasses import dataclass
from json import loads
from typing import Literal, cast

from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.action.write_persistence import (
    require_execution_binding,
)
from google_work_agent.application.use_cases.resource_ref.resolve_resource_ref import (
    ResolveResourceRefHandler,
    ResolveResourceRefQuery,
)
from google_work_agent.application.use_cases.verification.write_verification_projection import (
    build_expected_verification_projection,
    calculate_verification_subset_diff,
    normalize_actual_verification_projection,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadPort, JsonValue
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class SelectedResourceRefV1:
    schema_version: Literal[1]
    resource_ref_id: str
    connector_id: str
    resource_type: str
    resource_id: str
    parent_resource_id: str | None


@dataclass(frozen=True, slots=True)
class VerifyEffectQueryV1:
    run_id: str
    action_id: str
    execution_attempt_id: str
    effect: Literal["CREATE", "UPDATE", "DELETE", "SEND"]
    expected_effect: dict[str, object]
    target_resource_ref: SelectedResourceRefV1 | None


@dataclass(frozen=True, slots=True)
class VerificationResultV1:
    status: Literal["VERIFIED", "MISMATCH"]
    strategy: Literal["GET_COMPARE", "GET_ABSENT", "SENT_LOOKUP"]
    expected_normalized: dict[str, object]
    actual_normalized: dict[str, object] | None
    evidence_refs: list[str]
    reason_codes: list[str]


def _require_verification_source_state(
    action_status: str,
    attempt_status: ExecutionAttemptStatusV1,
) -> None:
    if (
        ActionStatusV1(action_status) is not ActionStatusV1.EXECUTED
        or attempt_status is not ExecutionAttemptStatusV1.SUCCEEDED
    ):
        raise ValueError("verification requires the current succeeded ExecutionAttempt")


class VerifyEffectHandler:
    def __init__(
        self,
        *,
        connector_read: ConnectorReadPort,
        tool_registry: SignedToolRegistry,
        connector_id: str = "google_workspace",
        unit_of_work_factory: Callable[[], UnitOfWork] | None = None,
        resolve_resource_ref: ResolveResourceRefHandler | None = None,
    ) -> None:
        self._connector_read = connector_read
        self._tool_registry = tool_registry
        self._connector_id = connector_id
        self._unit_of_work_factory = unit_of_work_factory
        self._resolve_resource_ref = resolve_resource_ref

    def project_persisted_query(
        self,
        *,
        run_id: str,
        action_id: str,
        execution_attempt_id: str,
    ) -> VerifyEffectQueryV1:
        if self._unit_of_work_factory is None or self._resolve_resource_ref is None:
            raise RuntimeError("persisted verification projection is not configured")
        with self._unit_of_work_factory() as unit_of_work:
            binding = require_execution_binding(
                unit_of_work,
                action_id=action_id,
                attempt_id=execution_attempt_id,
                run_id=run_id,
            )
            action = binding.action
            attempt = binding.attempt
            approval = binding.approval
            _require_verification_source_state(action.status, attempt.status)
            resource_ref_id = attempt.result_resource_ref_id or action.target_resource_ref_id
        resource_ref = (
            None
            if resource_ref_id is None
            else self._resolve_resource_ref(ResolveResourceRefQuery(resource_ref_id)).resource_ref
        )
        expected = cast(dict[str, object], loads(action.expected_json))
        if action.effect_type == "SEND" and approval is not None:
            expected = {**expected, "recovery_fingerprint": approval.recovery_fingerprint}
        target = (
            None
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
        return VerifyEffectQueryV1(
            run_id=run_id,
            action_id=action_id,
            execution_attempt_id=execution_attempt_id,
            effect=cast(Literal["CREATE", "UPDATE", "DELETE", "SEND"], action.effect_type),
            expected_effect=expected,
            target_resource_ref=target,
        )

    def run_id_for_action(self, action_id: str) -> str:
        if self._unit_of_work_factory is None:
            raise RuntimeError("persisted verification projection is not configured")
        with self._unit_of_work_factory() as unit_of_work:
            action = unit_of_work.actions.get(action_id)
            bundle = None if action is None else unit_of_work.plans.load_bundle(action.plan_id)
        if bundle is None:
            raise LookupError(f"plan not found for action: {action_id}")
        return bundle.plan.run_id

    def __call__(self, query: VerifyEffectQueryV1) -> VerificationResultV1:
        self._validate_query_binding(query)
        strategy = self._strategy(query.effect)
        tool_id, arguments = self._read_request(query, strategy)
        try:
            result = self._connector_read.execute_read(
                self._tool_registry.bind_required(self._connector_id, tool_id, "READ"),
                arguments,
            )
        except ConnectorOperationFailure as error:
            if strategy == "GET_ABSENT" and error.code is ConnectorFailureCode.NOT_FOUND:
                return VerificationResultV1(
                    "VERIFIED",
                    strategy,
                    query.expected_effect,
                    None,
                    [],
                    ["TARGET_ABSENT"],
                )
            raise
        if strategy == "SENT_LOOKUP":
            candidates = result.output.get("items", [])
            if not isinstance(candidates, list) or len(candidates) != 1:
                return VerificationResultV1(
                    "MISMATCH",
                    strategy,
                    _business_expected(query.expected_effect),
                    cast(dict[str, object], result.output),
                    [result.request_id],
                    ["MESSAGE_NOT_FOUND" if not candidates else "AMBIGUOUS_MESSAGES"],
                )
            candidate = candidates[0]
            if not isinstance(candidate, dict):
                raise TypeError("SENT_LOOKUP candidate must be an object")
            actual = _business_actual(
                cast(dict[str, object], candidate), normalizer_tool_name="gmail_send"
            )
            expected = _business_expected(query.expected_effect)
            diffs = calculate_verification_subset_diff(expected, actual)
            return VerificationResultV1(
                "VERIFIED" if not diffs else "MISMATCH",
                strategy,
                expected,
                actual,
                [result.request_id],
                [] if not diffs else ["EXPECTED_EFFECT_MISMATCH"],
            )
        raw_actual = result.output.get("item", result.output)
        if not isinstance(raw_actual, dict):
            raise TypeError("verification read result must contain an object")
        normalizer_tool_name = _normalizer_tool_name(query.target_resource_ref)
        actual = _business_actual(
            cast(dict[str, object], raw_actual),
            normalizer_tool_name=normalizer_tool_name,
        )
        if strategy == "GET_ABSENT":
            return VerificationResultV1(
                "MISMATCH",
                strategy,
                query.expected_effect,
                actual,
                [result.request_id],
                ["TARGET_STILL_PRESENT"],
            )
        expected = _business_expected(
            query.expected_effect,
            normalizer_tool_name=normalizer_tool_name,
        )
        diffs = calculate_verification_subset_diff(expected, actual)
        return VerificationResultV1(
            "VERIFIED" if not diffs else "MISMATCH",
            strategy,
            expected,
            actual,
            [result.request_id],
            [] if not diffs else ["EXPECTED_EFFECT_MISMATCH"],
        )

    def _validate_query_binding(self, query: VerifyEffectQueryV1) -> None:
        if self._unit_of_work_factory is None:
            return
        with self._unit_of_work_factory() as unit_of_work:
            binding = require_execution_binding(
                unit_of_work,
                action_id=query.action_id,
                attempt_id=query.execution_attempt_id,
                run_id=query.run_id,
            )
            action = binding.action
            attempt = binding.attempt
            _require_verification_source_state(action.status, attempt.status)
            expected = cast(dict[str, object], loads(action.expected_json))
            if action.tool_name in {"calendar_create_event", "calendar_update_event"}:
                required_expected = build_expected_verification_projection(
                    tool_name=action.tool_name,
                    arguments=loads(action.arguments_json),
                )
                if calculate_verification_subset_diff(
                    _business_expected(required_expected, normalizer_tool_name=action.tool_name),
                    _business_expected(expected, normalizer_tool_name=action.tool_name),
                ):
                    raise ValueError(
                        "persisted Calendar expectation does not cover approved arguments"
                    )
            if action.effect_type == "SEND":
                expected = {
                    **expected,
                    "recovery_fingerprint": binding.approval.recovery_fingerprint,
                }
            expected_resource_ref_id = (
                attempt.result_resource_ref_id or action.target_resource_ref_id
            )
        supplied_resource_ref_id = (
            None if query.target_resource_ref is None else query.target_resource_ref.resource_ref_id
        )
        if (
            query.effect != action.effect_type
            or query.expected_effect != expected
            or supplied_resource_ref_id != expected_resource_ref_id
        ):
            raise ValueError("verification query does not match persisted execution binding")

    @staticmethod
    def _strategy(
        effect: str,
    ) -> Literal["GET_COMPARE", "GET_ABSENT", "SENT_LOOKUP"]:
        if effect == "DELETE":
            return "GET_ABSENT"
        if effect == "SEND":
            return "SENT_LOOKUP"
        return "GET_COMPARE"

    @staticmethod
    def _read_request(
        query: VerifyEffectQueryV1, strategy: str
    ) -> tuple[str, dict[str, JsonValue]]:
        target = query.target_resource_ref
        if strategy == "SENT_LOOKUP":
            fingerprint = query.expected_effect.get("recovery_fingerprint")
            if not isinstance(fingerprint, str) or not fingerprint:
                raise ValueError("SENT_LOOKUP requires recovery_fingerprint")
            return "gmail_search_threads", {"query": fingerprint}
        if target is None:
            raise ValueError("verification requires a target resource")
        resource_type = target.resource_type.upper()
        if resource_type == "TASK":
            if target.parent_resource_id is None:
                raise ValueError("Task verification requires task-list identity")
            return "tasks_get_task", {
                "task_list_id": target.parent_resource_id,
                "task_id": target.resource_id,
            }
        if resource_type in {"CALENDAR", "CALENDAR_EVENT"}:
            if target.parent_resource_id is None:
                raise ValueError("Calendar verification requires calendar identity")
            return "calendar_get_event", {
                "calendar_id": target.parent_resource_id,
                "event_id": target.resource_id,
            }
        if resource_type == "GMAIL_DRAFT":
            return "gmail_get_draft", {"draft_id": target.resource_id}
        raise ValueError(f"unsupported verification resource type: {target.resource_type}")


def _business_expected(
    expected: dict[str, object],
    *,
    normalizer_tool_name: str | None = None,
) -> dict[str, object]:
    payload = expected.get("payload")
    business = cast(dict[str, object], payload) if isinstance(payload, dict) else expected
    filtered = {key: value for key, value in business.items() if key != "recovery_fingerprint"}
    if normalizer_tool_name is None:
        return filtered
    return _business_actual(filtered, normalizer_tool_name=normalizer_tool_name)


def _business_actual(actual: dict[str, object], *, normalizer_tool_name: str) -> dict[str, object]:
    payload = actual.get("payload")
    business = (
        actual
        if not isinstance(payload, dict)
        else {**{key: value for key, value in actual.items() if key != "payload"}, **payload}
    )
    normalized = normalize_actual_verification_projection(
        tool_name=normalizer_tool_name,
        actual={"payload": business},
    )
    normalized_payload = normalized.get("payload")
    if not isinstance(normalized_payload, dict):
        raise TypeError("verification normalizer must preserve the business payload")
    return cast(dict[str, object], normalized_payload)


def _normalizer_tool_name(target: SelectedResourceRefV1 | None) -> str:
    if target is None:
        raise ValueError("verification normalization requires a target resource")
    resource_type = target.resource_type.upper()
    if resource_type == "GMAIL_DRAFT":
        return "gmail_update_draft"
    if resource_type == "TASK":
        return "tasks_update_task"
    if resource_type in {"CALENDAR", "CALENDAR_EVENT"}:
        return "calendar_update_event"
    raise ValueError(f"unsupported verification resource type: {target.resource_type}")


__all__ = [
    "SelectedResourceRefV1",
    "VerificationResultV1",
    "VerifyEffectHandler",
    "VerifyEffectQueryV1",
]
