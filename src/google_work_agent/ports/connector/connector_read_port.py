"""Connector-neutral bounded READ boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ConnectorReadResultV1:
    schema_version: Literal[1]
    tool_id: str
    request_id: str
    output: dict[str, JsonValue]
    next_page_token: str | None
    total_count: int | None


class ConnectorReadPort(Protocol):
    def execute_read(
        self,
        binding: ValidatedConnectorToolBindingV1,
        tool_arguments: dict[str, JsonValue],
    ) -> ConnectorReadResultV1: ...


__all__ = ["ConnectorReadPort", "ConnectorReadResultV1", "JsonValue"]
