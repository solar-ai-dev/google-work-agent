"""Action lifecycle domain model and vocabulary."""

from dataclasses import dataclass
from enum import StrEnum
from json import JSONDecodeError, dumps, loads
from math import isfinite
from typing import cast

from google_work_agent.domain.results import InvariantViolationError


class PolicyViolationError(Exception):
    """A deterministic Action policy rejected the requested operation."""


class ActionStatusV1(StrEnum):
    PROPOSED = "PROPOSED"
    MODIFIED = "MODIFIED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    EXECUTING = "EXECUTING"
    UNKNOWN_RESULT = "UNKNOWN_RESULT"
    EXECUTED = "EXECUTED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    DEPENDENCY_BLOCKED = "DEPENDENCY_BLOCKED"
    MISMATCH = "MISMATCH"
    CANCELLED = "CANCELLED"


class EffectType(StrEnum):
    READ = "READ"
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    SEND = "SEND"
    DELETE = "DELETE"


class ApprovalRequirement(StrEnum):
    NONE = "NONE"
    REQUIRED = "REQUIRED"


class VerificationPolicy(StrEnum):
    NONE = "NONE"
    GET_COMPARE = "GET_COMPARE"
    SENT_LOOKUP = "SENT_LOOKUP"
    GET_ABSENT = "GET_ABSENT"


class RecoveryPolicy(StrEnum):
    NONE = "NONE"
    GET_TARGET = "GET_TARGET"
    RESOURCE_SEARCH = "RESOURCE_SEARCH"
    MESSAGE_SEARCH = "MESSAGE_SEARCH"


MAX_ACTION_RISK_JSON_BYTES = 16 * 1024


def canonicalize_action_risk(risk: object) -> str:
    """Validate and deterministically serialize one server-owned risk object."""

    _validate_json_value(risk, path="risk")
    if not isinstance(risk, dict):
        raise InvariantViolationError("action risk must be a JSON object")
    serialized = dumps(
        risk,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )
    if len(serialized.encode("utf-8")) > MAX_ACTION_RISK_JSON_BYTES:
        raise InvariantViolationError("action risk exceeds the 16 KiB storage limit")
    return serialized


def normalize_action_risk(risk: object) -> dict[str, object]:
    """Return an isolated structured copy after applying the risk contract."""

    return cast(dict[str, object], loads(canonicalize_action_risk(risk)))


def parse_action_risk_json(serialized: str) -> dict[str, object]:
    """Decode persisted risk without accepting corrupt or non-object JSON."""

    if len(serialized.encode("utf-8")) > MAX_ACTION_RISK_JSON_BYTES:
        raise InvariantViolationError("persisted action risk exceeds the 16 KiB storage limit")
    try:
        value = loads(serialized)
    except JSONDecodeError as error:
        raise InvariantViolationError("persisted action risk is not valid JSON") from error
    return normalize_action_risk(value)


def _validate_json_value(value: object, *, path: str) -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if isfinite(value):
            return
        raise InvariantViolationError(f"{path} contains a non-finite number")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvariantViolationError(f"{path} contains a non-string object key")
            _validate_json_value(item, path=f"{path}.{key}")
        return
    raise InvariantViolationError(f"{path} contains a non-JSON value")


@dataclass(frozen=True, slots=True)
class Action:
    id: str
    plan_id: str
    connector_id: str
    position: int
    tool_name: str
    effect_type: str
    approval_requirement: str
    verification_policy: str
    recovery_policy: str
    target_resource_ref_id: str | None
    status: str
    arguments_json: str
    arguments_hash: str
    expected_json: str
    risk: dict[str, object]
    version: int
    created_at_ms: int
    updated_at_ms: int


@dataclass(frozen=True, slots=True)
class ActionDependency:
    action_id: str
    depends_on_action_id: str


@dataclass(frozen=True, slots=True)
class ActionEvidence:
    action_id: str
    evidence_id: str


class ActionCommand(StrEnum):
    """Action lifecycle transition commands."""

    APPROVE_ACTION = "APPROVE_ACTION"
    MODIFY_ACTION = "MODIFY_ACTION"
    REJECT_ACTION = "REJECT_ACTION"
    REFRESH_EXPIRED_ACTION = "REFRESH_EXPIRED_ACTION"
    CLAIM_READ_ACTION = "CLAIM_READ_ACTION"
    COMPLETE_READ_ACTION = "COMPLETE_READ_ACTION"
    FINALIZE_READ_ACTION = "FINALIZE_READ_ACTION"
    FAIL_READ_ACTION = "FAIL_READ_ACTION"
    PREPARE_WRITE_RETRY = "PREPARE_WRITE_RETRY"
    CANCEL_PENDING_ACTION = "CANCEL_PENDING_ACTION"


def next_allowed_action_commands(
    current_status: ActionStatusV1, *, effect_type: EffectType
) -> tuple[ActionCommand, ...]:
    """Project only commands owned by the Action aggregate."""
    if effect_type is EffectType.READ:
        by_status = {
            ActionStatusV1.PROPOSED: (
                ActionCommand.MODIFY_ACTION,
                ActionCommand.REJECT_ACTION,
                ActionCommand.CLAIM_READ_ACTION,
            ),
            ActionStatusV1.EXECUTING: (
                ActionCommand.COMPLETE_READ_ACTION,
                ActionCommand.FAIL_READ_ACTION,
            ),
            ActionStatusV1.EXECUTED: (ActionCommand.FINALIZE_READ_ACTION,),
            ActionStatusV1.FAILED: (ActionCommand.MODIFY_ACTION,),
        }
    else:
        by_status = {
            ActionStatusV1.PROPOSED: (
                ActionCommand.APPROVE_ACTION,
                ActionCommand.MODIFY_ACTION,
                ActionCommand.REJECT_ACTION,
            ),
            ActionStatusV1.MODIFIED: (
                ActionCommand.APPROVE_ACTION,
                ActionCommand.MODIFY_ACTION,
                ActionCommand.REJECT_ACTION,
            ),
            ActionStatusV1.APPROVED: (
                ActionCommand.MODIFY_ACTION,
                ActionCommand.REJECT_ACTION,
                ActionCommand.CANCEL_PENDING_ACTION,
            ),
            ActionStatusV1.EXPIRED: (
                ActionCommand.REFRESH_EXPIRED_ACTION,
                ActionCommand.MODIFY_ACTION,
                ActionCommand.CANCEL_PENDING_ACTION,
            ),
            ActionStatusV1.FAILED: (
                ActionCommand.PREPARE_WRITE_RETRY,
                ActionCommand.MODIFY_ACTION,
            ),
        }
    return by_status.get(current_status, ())
