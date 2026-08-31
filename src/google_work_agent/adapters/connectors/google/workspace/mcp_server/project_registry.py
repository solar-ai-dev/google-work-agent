"""Google Workspace MCP registry projection and callable schema contracts."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from string import hexdigits
from typing import cast

from google_work_agent.ports.connector.mcp_client_port import MCPToolDescriptorV1

type JsonSchema = dict[str, object]


def _object_schema(
    properties: Mapping[str, object],
    *,
    required: tuple[str, ...] = (),
    additional_properties: bool = False,
) -> JsonSchema:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(required),
        "additionalProperties": additional_properties,
    }


_STRING: JsonSchema = {"type": "string"}


_NONEMPTY_STRING: JsonSchema = {"type": "string", "minLength": 1}


_NULLABLE_STRING: JsonSchema = {"type": ["string", "null"]}


_BOOLEAN: JsonSchema = {"type": "boolean"}


_PAGE_SIZE: JsonSchema = {"type": "integer", "minimum": 1, "maximum": 100}


_OPEN_OBJECT: JsonSchema = {"type": "object"}


_NULLABLE_OBJECT: JsonSchema = {"type": ["object", "null"]}


_SNAPSHOT_SCHEMA: JsonSchema = _object_schema(
    {
        "fixture_snapshot_id": _NONEMPTY_STRING,
        "resource_type": _NONEMPTY_STRING,
        "resource_id": _NONEMPTY_STRING,
        "parent_id": _NULLABLE_STRING,
        "related_resource_ids": {"type": "array", "items": _STRING},
        "version": _STRING,
        "recovery_fingerprint": _NULLABLE_STRING,
        "payload": _OPEN_OBJECT,
    },
    required=(
        "fixture_snapshot_id",
        "resource_type",
        "resource_id",
        "parent_id",
        "related_resource_ids",
        "version",
        "recovery_fingerprint",
        "payload",
    ),
)


_SNAPSHOT_ENVELOPE = _object_schema({"item": _SNAPSHOT_SCHEMA}, required=("item",))


_PAGE_ENVELOPE = _object_schema(
    {
        "items": {"type": "array", "items": _SNAPSHOT_SCHEMA},
        "next_page_token": _NULLABLE_STRING,
    },
    required=("items", "next_page_token"),
)


_FREEBUSY_ENVELOPE = _object_schema(
    {
        "calendars": {
            "type": "array",
            "items": _object_schema(
                {
                    "calendar_id": _NONEMPTY_STRING,
                    "intervals": {
                        "type": "array",
                        "items": _object_schema(
                            {
                                "start": _NONEMPTY_STRING,
                                "end": _NONEMPTY_STRING,
                                "transparency": _NONEMPTY_STRING,
                            },
                            required=("start", "end", "transparency"),
                        ),
                    },
                },
                required=("calendar_id", "intervals"),
            ),
        }
    },
    required=("calendars",),
)


_UI_THREAD_DETAIL_ENVELOPE = _object_schema(
    {
        "thread_id": _NONEMPTY_STRING,
        "message_id": _NONEMPTY_STRING,
        "rfc822_message_id": _NULLABLE_STRING,
        "sender_name": _NULLABLE_STRING,
        "sender_email": _NULLABLE_STRING,
        "recipients": {"type": "array", "items": _STRING},
        "cc": {"type": "array", "items": _STRING},
        "subject": _NULLABLE_STRING,
        "received_at": _NULLABLE_STRING,
        "body": _NULLABLE_STRING,
        "attachments": {
            "type": "array",
            "items": _object_schema(
                {
                    "message_id": _NONEMPTY_STRING,
                    "attachment_id": _NONEMPTY_STRING,
                    "filename": _STRING,
                    "mime_type": _STRING,
                    "size_bytes": {"type": ["integer", "null"], "minimum": 0},
                },
                required=(
                    "message_id",
                    "attachment_id",
                    "filename",
                    "mime_type",
                    "size_bytes",
                ),
            ),
        },
        "version": _STRING,
    },
    required=(
        "thread_id",
        "message_id",
        "rfc822_message_id",
        "sender_name",
        "sender_email",
        "recipients",
        "cc",
        "subject",
        "received_at",
        "body",
        "attachments",
        "version",
    ),
)


_ATTACHMENT_ENVELOPE = _object_schema(
    {
        "message_id": _NONEMPTY_STRING,
        "attachment_id": _NONEMPTY_STRING,
        "size_bytes": {"type": "integer", "minimum": 0},
        "sha256": _NONEMPTY_STRING,
        "data_base64url": _STRING,
    },
    required=("message_id", "attachment_id", "size_bytes", "sha256", "data_base64url"),
)


_RECOVERY_SEARCH_ENVELOPE = _object_schema(
    {"items": {"type": "array", "items": _SNAPSHOT_SCHEMA}},
    required=("items",),
)


@dataclass(frozen=True, slots=True)
class GoogleWorkspaceToolContract:
    tool_name: str
    input_schema_version: str
    output_schema_version: str
    input_schema: JsonSchema
    output_schema: JsonSchema

    @property
    def schema_hash(self) -> str:
        canonical = json.dumps(
            {
                "input_schema_version": self.input_schema_version,
                "output_schema_version": self.output_schema_version,
                "input_schema": self.input_schema,
                "output_schema": self.output_schema,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def manifest_schema_payload(self) -> dict[str, object]:
        # input_schema/output_schema are the SAME dict objects stored on this
        # frozen, process-wide-singleton contract (_CONTRACTS, built once at
        # import time) -- frozen only prevents reassigning the fields, not
        # mutating their contents. Callers that build a manifest payload and
        # then mutate it (as a "corrupt the delivered manifest" test fixture
        # legitimately does) would otherwise permanently corrupt the
        # canonical contract for the rest of the process. Deep-copy here so
        # every caller gets an independent value.
        return {
            "input_schema_version": self.input_schema_version,
            "output_schema_version": self.output_schema_version,
            "tool_schema_hash": self.schema_hash,
            "input_schema": deepcopy(self.input_schema),
            "output_schema": deepcopy(self.output_schema),
        }


class ToolContractViolation(ValueError):
    def __init__(self, *, tool_name: str, phase: str, errors: tuple[str, ...]) -> None:
        super().__init__(f"{tool_name} {phase} contract violation: {'; '.join(errors)}")
        self.tool_name = tool_name
        self.phase = phase
        self.errors = errors


def google_workspace_tool_contract(tool_name: str) -> GoogleWorkspaceToolContract:
    try:
        return _CONTRACTS[tool_name]
    except KeyError as error:
        raise KeyError(f"Google Workspace MCP tool contract not found: {tool_name}") from error


def list_google_workspace_tool_contracts() -> tuple[GoogleWorkspaceToolContract, ...]:
    return tuple(_CONTRACTS[name] for name in sorted(_CONTRACTS))


def validate_tool_input(tool_name: str, value: object) -> None:
    _validate_contract_phase(tool_name=tool_name, phase="input", value=value)


def validate_tool_output(tool_name: str, value: object) -> None:
    _validate_contract_phase(tool_name=tool_name, phase="output", value=value)


def _validate_contract_phase(*, tool_name: str, phase: str, value: object) -> None:
    contract = google_workspace_tool_contract(tool_name)
    schema = contract.input_schema if phase == "input" else contract.output_schema
    errors = tuple(_schema_errors(value, schema, path="$"))
    if errors:
        raise ToolContractViolation(tool_name=tool_name, phase=phase, errors=errors)


def _contract(
    tool_name: str, input_schema: JsonSchema, output_schema: JsonSchema
) -> GoogleWorkspaceToolContract:
    return GoogleWorkspaceToolContract(
        tool_name=tool_name,
        input_schema_version="v1",
        output_schema_version="v1",
        input_schema=input_schema,
        output_schema=output_schema,
    )


def _id_input(*names: str, optional: Mapping[str, object] | None = None) -> JsonSchema:
    properties: dict[str, object] = {name: _NONEMPTY_STRING for name in names}
    if optional:
        properties.update(optional)
    return _object_schema(properties, required=tuple(names))


def _write_input(*ids: str, payload_required: bool) -> JsonSchema:
    properties: dict[str, object] = {name: _NONEMPTY_STRING for name in ids}
    properties["claim_context"] = _NULLABLE_OBJECT
    required = list(ids)
    if payload_required:
        properties["payload"] = _OPEN_OBJECT
        required.append("payload")
    return _object_schema(properties, required=tuple(required))


def _page_input(*ids: str, extra: Mapping[str, object] | None = None) -> JsonSchema:
    properties: dict[str, object] = {name: _NONEMPTY_STRING for name in ids}
    properties.update({"page_token": _NULLABLE_STRING, "page_size": _PAGE_SIZE})
    if extra:
        properties.update(extra)
    return _object_schema(properties, required=tuple(ids))


def _build_contracts() -> dict[str, GoogleWorkspaceToolContract]:
    contracts: dict[str, GoogleWorkspaceToolContract] = {}

    def add(name: str, input_schema: JsonSchema, output_schema: JsonSchema) -> None:
        contracts[name] = _contract(name, input_schema, output_schema)

    add("calendar_get_event", _id_input("calendar_id", "event_id"), _SNAPSHOT_ENVELOPE)
    add(
        "calendar_create_event",
        _write_input("calendar_id", payload_required=True),
        _SNAPSHOT_ENVELOPE,
    )
    add(
        "calendar_delete_event",
        _write_input("calendar_id", "event_id", payload_required=False),
        _SNAPSHOT_ENVELOPE,
    )
    add("calendar_list_calendars", _page_input(), _PAGE_ENVELOPE)
    add(
        "calendar_list_events",
        _page_input(
            "calendar_id",
            extra={
                "time_min": _NULLABLE_STRING,
                "time_max": _NULLABLE_STRING,
                "single_events": _BOOLEAN,
                "order_by": _NULLABLE_STRING,
            },
        ),
        _PAGE_ENVELOPE,
    )
    add(
        "calendar_query_freebusy",
        _object_schema(
            {
                "calendar_ids": {
                    "type": "array",
                    "items": _NONEMPTY_STRING,
                    "minItems": 1,
                    "maxItems": 20,
                },
                "time_min": _NONEMPTY_STRING,
                "time_max": _NONEMPTY_STRING,
            },
            required=("calendar_ids", "time_min", "time_max"),
        ),
        _FREEBUSY_ENVELOPE,
    )
    add(
        "calendar_update_event",
        _write_input("calendar_id", "event_id", payload_required=True),
        _SNAPSHOT_ENVELOPE,
    )
    add("gmail_create_draft", _write_input(payload_required=True), _SNAPSHOT_ENVELOPE)
    add("gmail_get_draft", _id_input("draft_id"), _SNAPSHOT_ENVELOPE)
    add("gmail_get_message", _id_input("message_id"), _SNAPSHOT_ENVELOPE)
    add("gmail_get_thread", _id_input("thread_id"), _SNAPSHOT_ENVELOPE)
    add(
        "gmail_search_threads",
        _object_schema(
            {
                "query": _STRING,
                "page_token": _NULLABLE_STRING,
                "page_size": _PAGE_SIZE,
                "include_thread_metadata": _BOOLEAN,
            },
            required=("query",),
        ),
        _PAGE_ENVELOPE,
    )
    add(
        "gmail_send",
        _id_input(
            "draft_id",
            optional={
                "recovery_fingerprint": _NULLABLE_STRING,
                "claim_context": _NULLABLE_OBJECT,
            },
        ),
        _SNAPSHOT_ENVELOPE,
    )
    add(
        "gmail_update_draft",
        _write_input("draft_id", payload_required=True),
        _SNAPSHOT_ENVELOPE,
    )
    add(
        "tasks_create_task",
        _write_input("task_list_id", payload_required=True),
        _SNAPSHOT_ENVELOPE,
    )
    add("tasks_get_task", _id_input("task_list_id", "task_id"), _SNAPSHOT_ENVELOPE)
    add("tasks_list_tasklists", _page_input(), _PAGE_ENVELOPE)
    add(
        "tasks_list_tasks",
        _page_input(
            "task_list_id",
            extra={
                "show_completed": _BOOLEAN,
                "show_hidden": _BOOLEAN,
                "show_deleted": _BOOLEAN,
            },
        ),
        _PAGE_ENVELOPE,
    )
    add(
        "tasks_update_task",
        _write_input("task_list_id", "task_id", payload_required=True),
        _SNAPSHOT_ENVELOPE,
    )
    add(
        "tasks_delete_task",
        _write_input("task_list_id", "task_id", payload_required=False),
        _SNAPSHOT_ENVELOPE,
    )
    add("gmail_get_ui_thread_detail", _id_input("thread_id"), _UI_THREAD_DETAIL_ENVELOPE)
    add(
        "gmail_get_attachment",
        _id_input("message_id", "attachment_id"),
        _ATTACHMENT_ENVELOPE,
    )
    add(
        "search_by_recovery_fingerprint",
        _object_schema(
            {
                "resource_type": {
                    "type": "string",
                    "enum": [
                        "gmail_thread",
                        "gmail_message",
                        "gmail_draft",
                        "task_list",
                        "task",
                        "calendar",
                        "calendar_event",
                        "calendar_freebusy",
                    ],
                },
                "recovery_fingerprint": _NONEMPTY_STRING,
            },
            required=("resource_type", "recovery_fingerprint"),
        ),
        _RECOVERY_SEARCH_ENVELOPE,
    )
    return contracts


def _schema_errors(value: object, schema: Mapping[str, object], *, path: str) -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, str):
        if not _matches_type(value, expected_type):
            return [f"{path} must be {expected_type}"]
    elif isinstance(expected_type, list):
        types = tuple(item for item in expected_type if isinstance(item, str))
        if not any(_matches_type(value, item) for item in types):
            return [f"{path} must be one of {types}"]

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and value not in enum_values:
        errors.append(f"{path} must be one of {enum_values}")

    if isinstance(value, dict):
        properties = schema.get("properties")
        known = properties if isinstance(properties, Mapping) else {}
        required = schema.get("required")
        required_names = required if isinstance(required, list) else []
        for name in required_names:
            if isinstance(name, str) and name not in value:
                errors.append(f"{path}.{name} is required")
        if schema.get("additionalProperties") is False:
            for name in value:
                if name not in known:
                    errors.append(f"{path}.{name} is not allowed")
        for name, item in value.items():
            child = known.get(name)
            if isinstance(name, str) and isinstance(child, Mapping):
                errors.extend(_schema_errors(item, child, path=f"{path}.{name}"))

    if isinstance(value, list):
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if isinstance(min_items, int) and len(value) < min_items:
            errors.append(f"{path} must contain at least {min_items} items")
        if isinstance(max_items, int) and len(value) > max_items:
            errors.append(f"{path} must contain at most {max_items} items")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                errors.extend(_schema_errors(item, item_schema, path=f"{path}[{index}]"))

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(f"{path} must have length >= {min_length}")

    if isinstance(value, int) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, int | float) and value < minimum:
            errors.append(f"{path} must be >= {minimum}")
        if isinstance(maximum, int | float) and value > maximum:
            errors.append(f"{path} must be <= {maximum}")
    return errors


def _matches_type(value: object, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


_CONTRACTS = _build_contracts()


INTERNAL_CAPABILITY_REGISTRY_VERSION = "2026-08-20.p0"


class MCPInternalCapabilityCategory(StrEnum):
    """Non-Agent callable capability categories exposed by the MCP child."""

    UI_READ = "UI_READ"
    ATTACHMENT_READ = "ATTACHMENT_READ"
    RECOVERY_READ = "RECOVERY_READ"


@dataclass(frozen=True, slots=True)
class MCPInternalCapability:
    """Versioned declaration for one non-Agent MCP callable."""

    tool_name: str
    category: MCPInternalCapabilityCategory
    registry_version: str = INTERNAL_CAPABILITY_REGISTRY_VERSION

    @property
    def contract(self) -> GoogleWorkspaceToolContract:
        return google_workspace_tool_contract(self.tool_name)

    @property
    def input_schema_version(self) -> str:
        return self.contract.input_schema_version

    @property
    def output_schema_version(self) -> str:
        return self.contract.output_schema_version

    @property
    def tool_schema_hash(self) -> str:
        return self.contract.schema_hash

    def to_manifest_payload(self) -> dict[str, object]:
        return {
            "tool_name": self.tool_name,
            "category": self.category.value,
            "registry_version": self.registry_version,
            **self.contract.manifest_schema_payload(),
        }


def build_google_workspace_internal_capabilities() -> tuple[MCPInternalCapability, ...]:
    """Return the complete Google Workspace non-Agent callable surface."""

    return (
        MCPInternalCapability(
            tool_name="gmail_get_ui_thread_detail",
            category=MCPInternalCapabilityCategory.UI_READ,
        ),
        MCPInternalCapability(
            tool_name="search_by_recovery_fingerprint",
            category=MCPInternalCapabilityCategory.RECOVERY_READ,
        ),
    )


_DEFAULT_PROJECTION = Path(__file__).with_name("tool_descriptor_projection.json")


_PROJECTION_PATH_ENV = "GWA_MCP_TOOL_PROJECTION_PATH"


_PROJECTION_FIELDS = frozenset(
    {"schema_version", "connector_id", "registry_manifest_hash", "tools"}
)


_TOOL_FIELDS = frozenset(
    {
        "schema_version",
        "connector_id",
        "tool_id",
        "input_schema_ref",
        "output_schema_ref",
        "registry_entry_hash",
    }
)


def project_registry(path: Path | None = None) -> tuple[MCPToolDescriptorV1, ...]:
    projection_path = path or Path(os.environ.get(_PROJECTION_PATH_ENV, _DEFAULT_PROJECTION))
    decoded = json.loads(projection_path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("tool descriptor projection must be an object")
    payload = cast(dict[str, object], decoded)
    _require_exact_fields(payload, _PROJECTION_FIELDS, "tool descriptor projection")
    if payload.get("schema_version") != 1 or payload.get("connector_id") != "google_workspace":
        raise ValueError("invalid Google Workspace MCP projection identity")
    raw_tools = payload.get("tools")
    if not isinstance(raw_tools, list) or not raw_tools:
        raise ValueError("tool descriptor projection tools must be a non-empty list")
    tools = tuple(_descriptor(_require_object(item)) for item in raw_tools)
    if len({tool.tool_id for tool in tools}) != len(tools):
        raise ValueError("duplicate tool_id in Google Workspace MCP projection")
    return tuple(sorted(tools, key=lambda tool: tool.tool_id))


def registry_manifest_hash(path: Path | None = None) -> str:
    projection_path = path or Path(os.environ.get(_PROJECTION_PATH_ENV, _DEFAULT_PROJECTION))
    payload = cast(dict[str, object], json.loads(projection_path.read_text(encoding="utf-8")))
    value = str(payload.get("registry_manifest_hash", ""))
    _validate_hash(value, "registry_manifest_hash")
    return value


def get_projected_tool(tool_id: str) -> MCPToolDescriptorV1 | None:
    return next((tool for tool in project_registry() if tool.tool_id == tool_id), None)


def _descriptor(payload: dict[str, object]) -> MCPToolDescriptorV1:
    _require_exact_fields(payload, _TOOL_FIELDS, "MCPToolDescriptorV1")
    if payload.get("schema_version") != 1 or payload.get("connector_id") != "google_workspace":
        raise ValueError("invalid projected tool identity")
    _validate_hash(str(payload.get("registry_entry_hash", "")), "registry_entry_hash")
    return MCPToolDescriptorV1(
        schema_version=1,
        connector_id=str(payload["connector_id"]),
        tool_id=str(payload["tool_id"]),
        input_schema_ref=str(payload["input_schema_ref"]),
        output_schema_ref=str(payload["output_schema_ref"]),
        registry_entry_hash=str(payload["registry_entry_hash"]),
    )


def _require_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("MCPToolDescriptorV1 must be an object")
    return cast(dict[str, object], value)


def _require_exact_fields(
    payload: dict[str, object], expected: frozenset[str], contract_name: str
) -> None:
    actual = frozenset(payload)
    if actual != expected:
        raise ValueError(
            f"{contract_name} fields mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _validate_hash(value: str, field_name: str) -> None:
    if (
        len(value) != 64
        or value != value.lower()
        or any(character not in hexdigits for character in value)
    ):
        raise ValueError(f"{field_name} must be lowercase SHA-256")


__all__ = [
    "INTERNAL_CAPABILITY_REGISTRY_VERSION",
    "GoogleWorkspaceToolContract",
    "MCPInternalCapability",
    "ToolContractViolation",
    "build_google_workspace_internal_capabilities",
    "get_projected_tool",
    "google_workspace_tool_contract",
    "project_registry",
    "registry_manifest_hash",
    "validate_tool_input",
    "validate_tool_output",
]
