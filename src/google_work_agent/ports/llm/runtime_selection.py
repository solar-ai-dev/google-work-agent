"""Immutable release-derived local LLM runtime selection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from google_work_agent.ports.llm.local_model_profile import LocalModelProfileV1
from google_work_agent.ports.llm.structured_inference_contracts import ApprovedModelInfo

OLLAMA_FIXED_LOOPBACK_ENDPOINT = "http://127.0.0.1:11434"


class LocalRuntimeActivationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DEFERRED_UNTIL_PRODUCT_DECISION = "DEFERRED_UNTIL_PRODUCT_DECISION"
    DISABLED_BY_DEPLOYMENT_PROFILE = "DISABLED_BY_DEPLOYMENT_PROFILE"


@dataclass(frozen=True, slots=True)
class LocalRuntimeRequirementsV1:
    minimum_cpu_logical_cores: int
    minimum_ram_bytes: int
    minimum_vram_bytes: int
    supported_os: Literal["WINDOWS"]
    supported_architecture: Literal["AMD64"]


@dataclass(frozen=True, slots=True)
class LlmRuntimeSelectionV1:
    schema_version: Literal[1]
    deployment_profile: Literal["API_ONLY", "LOCAL_CAPABLE"]
    selected_model: ApprovedModelInfo | None
    ollama_endpoint_policy: Literal["FIXED_LOOPBACK_OLLAMA_V1"]
    model_manifest_hash: str | None
    product_decision_hash: str | None
    local_runtime_activation_status: LocalRuntimeActivationStatus
    requirements: LocalRuntimeRequirementsV1 | None
    release_version: str
    approved_models: tuple[ApprovedModelInfo, ...] = ()
    local_model_profile: LocalModelProfileV1 | None = None

    @property
    def selected_model_id(self) -> str | None:
        return None if self.selected_model is None else self.selected_model.model_id

    def get_approved_model(self, model_id: str) -> ApprovedModelInfo | None:
        candidates = self.approved_models or (
            () if self.selected_model is None else (self.selected_model,)
        )
        return next((model for model in candidates if model.model_id == model_id), None)

    @property
    def ollama_endpoint(self) -> str:
        return OLLAMA_FIXED_LOOPBACK_ENDPOINT

    @property
    def is_active(self) -> bool:
        return self.local_runtime_activation_status is LocalRuntimeActivationStatus.ACTIVE


__all__ = [
    "LlmRuntimeSelectionV1",
    "LocalRuntimeActivationStatus",
    "LocalRuntimeRequirementsV1",
    "OLLAMA_FIXED_LOOPBACK_ENDPOINT",
]
