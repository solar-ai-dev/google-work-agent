"""API-facing confirmation orchestration over canonical lifecycle handlers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, cast

from google_work_agent.application.agents.request_understanding.validate_intent import (
    validate_intent,
)
from google_work_agent.application.agents.work_analysis.assemble_work_analysis import (
    work_analysis_confirmation_context_hash,
)
from google_work_agent.application.orchestration.contracts import (
    ConfirmationResponseProjectionV1,
    validate_confirmation_response_projection_v1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    RequestIntentV2,
    StateArtifactRefV1,
)
from google_work_agent.application.orchestration.scope_expansion import (
    build_policy_confirmation_receipt,
)
from google_work_agent.application.use_cases.run.policy_confirmation_receipt import (
    PolicyConfirmationReceiptV1,
)
from google_work_agent.application.use_cases.run.resume_confirmation import (
    ResumeConfirmationCommand,
    ResumeConfirmationHandler,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
)
from google_work_agent.ports.system.contracts.workflow_handoff import (
    AgentNodeResumeTargetV2,
    RunExecutionAcceptedV1,
)


class ResumeTargetValidator(Protocol):
    def validate(self, ref: AgentNodeResumeTargetV2) -> None: ...


@dataclass(frozen=True, slots=True)
class ConfirmRunCommand:
    command_id: str
    request_hash: str
    run_id: str
    expected_version: int
    interrupt_id: str
    response_kind: str
    selected_option: str | None
    free_text: str | None


@dataclass(frozen=True, slots=True)
class ConfirmRunResult:
    applied: bool
    result_code: str
    run_id: str
    run_status: str
    run_version: int
    should_enqueue: bool
    request_replayed: bool
    conflict_detail: str | None = None


class ConfirmRunHandler:
    def __init__(
        self,
        *,
        resolve_pending_confirmation: Callable[[str], Mapping[str, object] | None],
        resume_confirmation: ResumeConfirmationHandler,
        resume_target_registry: ResumeTargetValidator,
        schedule_run_execution: Callable[[ScheduleRunExecutionCommand], RunExecutionAcceptedV1],
        id_factory: Callable[[], str],
    ) -> None:
        self._resolve_pending_confirmation = resolve_pending_confirmation
        self._resume_confirmation = resume_confirmation
        self._resume_target_registry = resume_target_registry
        self._schedule_run_execution = schedule_run_execution
        self._id_factory = id_factory

    def __call__(self, command: ConfirmRunCommand) -> ConfirmRunResult:
        replayed = self._resume_confirmation.replay_existing(
            command_id=command.command_id,
            request_hash=command.request_hash,
            run_id=command.run_id,
        )
        if replayed is not None:
            return ConfirmRunResult(
                applied=replayed.applied,
                result_code=replayed.result_code,
                run_id=replayed.run_id,
                run_status=replayed.current_status,
                run_version=replayed.current_version,
                should_enqueue=False,
                request_replayed=replayed.request_replayed,
                conflict_detail=replayed.conflict_detail,
            )
        authority = self._resolve_pending_confirmation(command.run_id)
        if authority is None:
            return _conflict(command, "persisted pending confirmation is unavailable")
        try:
            projection = validate_confirmation_response_projection_v1(
                {
                    "schema_version": 1,
                    "response_kind": command.response_kind,
                    "selected_option": command.selected_option,
                    "free_text": command.free_text,
                }
            )
            self._validate_authority(command, authority, projection)
            target = _target(authority)
            self._resume_target_registry.validate(target)
            checkpoint_id = _required_string(authority, "checkpoint_id")
            checkpoint_generation = authority.get("checkpoint_generation")
            if not isinstance(checkpoint_generation, int) or checkpoint_generation < 1:
                raise ValueError("pending confirmation checkpoint generation is invalid")
            policy_receipt = self._policy_receipt(authority, projection)
        except ValueError as error:
            return _conflict(command, str(error))

        resumed = self._resume_confirmation(
            ResumeConfirmationCommand(
                command_id=command.command_id,
                request_hash=command.request_hash,
                run_id=command.run_id,
                expected_version=command.expected_version,
                interrupt_id=command.interrupt_id,
                pre_confirmation_status=_required_string(authority, "pre_confirmation_status"),
                resume_target=target,
                checkpoint_id=checkpoint_id,
                checkpoint_generation=checkpoint_generation,
                confirmation_response=projection,
                policy_confirmation_receipt=policy_receipt,
            )
        )
        accepted = False
        if resumed.applied and resumed.handoff_id is not None:
            accepted = self._schedule_run_execution(
                ScheduleRunExecutionCommand(handoff_id=resumed.handoff_id)
            ).accepted
        return ConfirmRunResult(
            applied=resumed.applied,
            result_code=resumed.result_code,
            run_id=resumed.run_id,
            run_status=resumed.current_status,
            run_version=resumed.current_version,
            should_enqueue=accepted,
            request_replayed=resumed.request_replayed,
            conflict_detail=resumed.conflict_detail,
        )

    @staticmethod
    def _validate_authority(
        command: ConfirmRunCommand,
        authority: Mapping[str, object],
        projection: ConfirmationResponseProjectionV1,
    ) -> None:
        if authority.get("interrupt_id") != command.interrupt_id:
            raise ValueError("interrupt_id does not match the pending confirmation")
        options = authority.get("options")
        if not isinstance(options, list) or not all(
            isinstance(option, str) and option for option in options
        ):
            raise ValueError("pending confirmation options are invalid")
        if projection["response_kind"] == "OPTION":
            if projection["selected_option"] not in options:
                raise ValueError("selected_option is outside the pending option set")
        elif projection["response_kind"] == "FREE_TEXT" and options:
            raise ValueError("closed-choice confirmation requires OPTION or DECLINE")

    def _policy_receipt(
        self,
        authority: Mapping[str, object],
        projection: ConfirmationResponseProjectionV1,
    ) -> PolicyConfirmationReceiptV1 | None:
        raw = authority.get("policy_confirmation")
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise ValueError("pending policy confirmation authority is invalid")
        confirmation_kind = raw.get("confirmation_kind")
        if confirmation_kind in {"DUPLICATE_OVERRIDE", "CONFLICT_OVERRIDE"}:
            raw_based_on = raw.get("based_on")
            if not isinstance(raw_based_on, list):
                raise ValueError("Work Analysis confirmation lineage is invalid")
            based_on: list[dict[str, object]] = []
            for item in raw_based_on:
                if not isinstance(item, Mapping) or set(item) != {"artifact_id", "revision"}:
                    raise ValueError("Work Analysis confirmation lineage is invalid")
                artifact_id, revision = item.get("artifact_id"), item.get("revision")
                if (
                    not isinstance(artifact_id, str)
                    or not artifact_id
                    or not isinstance(revision, int)
                    or isinstance(revision, bool)
                    or revision < 1
                ):
                    raise ValueError("Work Analysis confirmation lineage is invalid")
                based_on.append({"artifact_id": artifact_id, "revision": revision})
            interrupt_id = _required_string(authority, "interrupt_id")
            override_decision: Literal["APPROVED", "DECLINED"] = (
                "APPROVED"
                if projection["response_kind"] == "OPTION"
                and projection["selected_option"] == "APPROVED"
                else "DECLINED"
            )
            return {
                "schema_version": 1,
                "meta": {
                    "artifact_id": self._id_factory(),
                    "revision": 1,
                    "based_on": cast(list[StateArtifactRefV1], based_on),
                },
                "interrupt_id": interrupt_id,
                "confirmation_kind": cast(
                    Literal["DUPLICATE_OVERRIDE", "CONFLICT_OVERRIDE"], confirmation_kind
                ),
                "decision": override_decision,
                "semantic_owner_id": "WORK_ANALYSIS",
                "decision_context_hash": work_analysis_confirmation_context_hash(
                    confirmation_kind=confirmation_kind,
                    interrupt_id=interrupt_id,
                    based_on=cast(list[StateArtifactRefV1], based_on),
                ),
                "affected_route_ids": [],
                "affected_resource_refs": [],
            }
        if confirmation_kind != "SCOPE_EXPANSION":
            raise ValueError("pending policy confirmation authority is invalid")
        request_intent = validate_intent(raw.get("request_intent"), require_meta=True)
        required_resource_types = _string_tuple(raw, "required_resource_types")
        reason_codes = _string_tuple(raw, "reason_codes")
        affected_route_ids = list(_string_tuple(raw, "affected_route_ids"))
        decision: Literal["APPROVED", "DECLINED"] = (
            "APPROVED"
            if projection["response_kind"] == "OPTION"
            and projection["selected_option"] == "APPROVED"
            else "DECLINED"
        )
        return build_policy_confirmation_receipt(
            id_factory=self._id_factory,
            interrupt_id=_required_string(authority, "interrupt_id"),
            decision=decision,
            request_intent=cast(RequestIntentV2, request_intent),
            required_resource_types=required_resource_types,
            reason_codes=reason_codes,
            affected_route_ids=affected_route_ids,
        )


def _target(authority: Mapping[str, object]) -> AgentNodeResumeTargetV2:
    raw = authority.get("resume_target")
    if not isinstance(raw, Mapping):
        raise ValueError("pending confirmation resume target is missing")
    try:
        return AgentNodeResumeTargetV2(**dict(raw))
    except TypeError as error:
        raise ValueError("pending confirmation resume target is invalid") from error


def _required_string(value: Mapping[str, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise ValueError(f"pending confirmation {field} is invalid")
    return item


def _string_tuple(value: Mapping[str, object], field: str) -> tuple[str, ...]:
    raw = value.get(field)
    if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
        raise ValueError(f"pending confirmation {field} is invalid")
    return tuple(raw)


def _conflict(command: ConfirmRunCommand, detail: str) -> ConfirmRunResult:
    return ConfirmRunResult(
        applied=False,
        result_code="STATE_CONFLICT",
        run_id=command.run_id,
        run_status="WAITING_CONFIRMATION",
        run_version=command.expected_version,
        should_enqueue=False,
        request_replayed=False,
        conflict_detail=detail,
    )


__all__ = ["ConfirmRunCommand", "ConfirmRunHandler", "ConfirmRunResult"]
