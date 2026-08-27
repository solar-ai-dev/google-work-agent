"""Validated Tool binding accepted by Connector read/write Ports."""

from __future__ import annotations

from dataclasses import dataclass
from string import hexdigits
from typing import Literal


@dataclass(frozen=True, slots=True)
class ValidatedConnectorToolBindingV1:
    """Immutable projection materialized by the Application Tool Registry."""

    schema_version: Literal[1]
    connector_id: str
    resource_type: str
    tool_id: str
    effect: Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]
    input_schema_ref: str
    output_schema_ref: str
    registry_entry_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported ValidatedConnectorToolBindingV1 schema_version")
        for field_name in (
            "connector_id",
            "resource_type",
            "tool_id",
            "input_schema_ref",
            "output_schema_ref",
            "registry_entry_hash",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} is required")
        if self.effect not in {"READ", "CREATE", "UPDATE", "SEND", "DELETE"}:
            raise ValueError("unsupported connector tool effect")
        if (
            len(self.registry_entry_hash) != 64
            or self.registry_entry_hash != self.registry_entry_hash.lower()
            or any(character not in hexdigits for character in self.registry_entry_hash)
        ):
            raise ValueError("registry_entry_hash must be lowercase SHA-256")


__all__ = ["ValidatedConnectorToolBindingV1"]
