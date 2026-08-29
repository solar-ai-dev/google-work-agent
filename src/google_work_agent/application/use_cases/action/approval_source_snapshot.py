"""Build the Action-owner-local source-resource snapshot used by Approval use cases."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from json import JSONDecodeError, loads

from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import EffectType, PolicyViolationError
from google_work_agent.domain.resource_ref.model import ResourceRef as ResourceRefRecord
from google_work_agent.ports.connector.contracts.google_workspace import ResourceType

_RESOURCE_AUTHORITY_FIELDS = frozenset(
    {"resource_type", "resource_id", "parent_id", "version", "payload"}
)


@dataclass(frozen=True, slots=True)
class _UpdateSourceContract:
    resource_type: ResourceType
    stored_resource_type: str
    resource_id_argument: str
    parent_id_argument: str | None


_UPDATE_SOURCE_CONTRACTS = {
    "gmail_update_draft": _UpdateSourceContract(
        resource_type=ResourceType.GMAIL_DRAFT,
        stored_resource_type=ResourceType.GMAIL_DRAFT.value,
        resource_id_argument="draft_id",
        parent_id_argument=None,
    ),
    "tasks_update_task": _UpdateSourceContract(
        resource_type=ResourceType.TASK,
        stored_resource_type=ResourceType.TASK.value,
        resource_id_argument="task_id",
        parent_id_argument="task_list_id",
    ),
    "calendar_update_event": _UpdateSourceContract(
        resource_type=ResourceType.CALENDAR_EVENT,
        stored_resource_type=ResourceType.CALENDAR_EVENT.value,
        resource_id_argument="event_id",
        parent_id_argument="calendar_id",
    ),
}


def build_approval_source_snapshot(
    *,
    action: ActionRecord,
    plan_run_id: str,
    resource_ref: ResourceRefRecord | None,
) -> dict[str, object]:
    """Project persisted Action/ResourceRef authority into the Approval snapshot."""

    try:
        effect_type = EffectType(action.effect_type)
    except ValueError as error:
        raise PolicyViolationError("action effect type is invalid") from error
    if effect_type is not EffectType.UPDATE:
        return {}

    contract = _UPDATE_SOURCE_CONTRACTS.get(action.tool_name)
    if contract is None:
        raise PolicyViolationError(
            f"UPDATE approval source contract is not registered: {action.tool_name}"
        )
    if action.target_resource_ref_id is None:
        raise PolicyViolationError("UPDATE approval requires target resource authority")
    if resource_ref is None or resource_ref.id != action.target_resource_ref_id:
        raise PolicyViolationError("UPDATE approval target resource authority is missing")
    if resource_ref.run_id != plan_run_id:
        raise PolicyViolationError("UPDATE approval resource authority belongs to another run")
    if resource_ref.connector_id != action.connector_id:
        raise PolicyViolationError("UPDATE approval resource connector binding mismatch")
    if resource_ref.resource_type != contract.stored_resource_type:
        raise PolicyViolationError("UPDATE approval resource type binding mismatch")
    if not resource_ref.resource_id:
        raise PolicyViolationError("UPDATE approval resource id is missing")
    if not resource_ref.version_token:
        raise PolicyViolationError("UPDATE approval resource version is missing")

    try:
        arguments = loads(action.arguments_json)
    except (JSONDecodeError, TypeError) as error:
        raise PolicyViolationError("UPDATE action arguments are invalid") from error
    if not isinstance(arguments, dict):
        raise PolicyViolationError("UPDATE action arguments must be an object")

    expected_resource_id = _required_text(
        arguments.get(contract.resource_id_argument),
        contract.resource_id_argument,
    )
    if resource_ref.resource_id != expected_resource_id:
        raise PolicyViolationError("UPDATE approval resource id does not match action arguments")

    if contract.parent_id_argument is not None:
        expected_parent_id = _required_text(
            arguments.get(contract.parent_id_argument),
            contract.parent_id_argument,
        )
        if resource_ref.parent_resource_id != expected_parent_id:
            raise PolicyViolationError(
                "UPDATE approval parent resource does not match action arguments"
            )

    snapshot: dict[str, object] = {
        "resource_type": contract.resource_type.value,
        "resource_id": resource_ref.resource_id,
        "version": resource_ref.version_token,
    }
    if resource_ref.parent_resource_id is not None:
        snapshot["parent_id"] = resource_ref.parent_resource_id
    return snapshot


def merge_approval_snapshot_metadata(
    source_snapshot: Mapping[str, object],
    *metadata_snapshots: Mapping[str, object],
) -> dict[str, object]:
    """Merge policy metadata without allowing it to replace resource authority."""

    merged = dict(source_snapshot)
    for metadata in metadata_snapshots:
        collision = _RESOURCE_AUTHORITY_FIELDS.intersection(metadata)
        if collision:
            names = ", ".join(sorted(collision))
            raise PolicyViolationError(
                f"approval metadata cannot overwrite source resource authority: {names}"
            )
        merged.update(metadata)
    return merged


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise PolicyViolationError(f"{field_name} is required for UPDATE approval")
    return value
