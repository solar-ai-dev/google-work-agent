"""Process-local external-component circuit boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class ComponentCircuitKeyV1:
    schema_version: Literal[1]
    kind: Literal["CONNECTOR", "LLM_RUNTIME"]
    connector_id: str | None
    llm_runtime: Literal["API_LLM", "LOCAL_GPU"] | None

    def __post_init__(self) -> None:
        connector_valid = (
            self.kind == "CONNECTOR" and bool(self.connector_id) and self.llm_runtime is None
        )
        llm_valid = (
            self.kind == "LLM_RUNTIME"
            and self.connector_id is None
            and self.llm_runtime in {"API_LLM", "LOCAL_GPU"}
        )
        if self.schema_version != 1 or not (connector_valid or llm_valid):
            raise ValueError("invalid ComponentCircuitKeyV1 binding")


@dataclass(frozen=True, slots=True)
class ComponentCircuitStateV1:
    schema_version: Literal[1]
    key: ComponentCircuitKeyV1
    state: Literal["CLOSED", "OPEN"]
    consecutive_technical_failures: int
    retry_at_ms: int | None
    last_failure_code: str | None


class ComponentCircuitStatePort(Protocol):
    def get_state(self, key: ComponentCircuitKeyV1) -> ComponentCircuitStateV1: ...

    def record_technical_failure(
        self, key: ComponentCircuitKeyV1, failure_code: str, now_ms: int
    ) -> ComponentCircuitStateV1: ...

    def record_success(
        self, key: ComponentCircuitKeyV1, now_ms: int
    ) -> ComponentCircuitStateV1: ...


__all__ = ["ComponentCircuitKeyV1", "ComponentCircuitStatePort", "ComponentCircuitStateV1"]
