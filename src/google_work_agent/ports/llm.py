"""LLM runtime contracts shared across API and local adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class RequestedRuntimeMode(StrEnum):
    API_LLM = "API_LLM"
    LOCAL_GPU = "LOCAL_GPU"
    AUTO = "AUTO"


class ActualRuntime(StrEnum):
    API_LLM = "API_LLM"
    LOCAL_GPU = "LOCAL_GPU"


class LLMProviderKind(StrEnum):
    API_PROVIDER = "API_PROVIDER"
    OLLAMA = "OLLAMA"


class LLMCredentialState(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    KEYRING = "KEYRING"
    SESSION_MEMORY = "SESSION_MEMORY"
    UNAVAILABLE = "UNAVAILABLE"


class AvailabilityState(StrEnum):
    AVAILABLE = "AVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNAVAILABLE = "UNAVAILABLE"
    BLOCKED = "BLOCKED"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


class HardwareCapabilityStatus(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"
    NOT_VALIDATED = "NOT_VALIDATED"
    INSUFFICIENT = "INSUFFICIENT"
    VALIDATED = "VALIDATED"


class LLMErrorCode(StrEnum):
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    API_KEY_MISSING = "API_KEY_MISSING"
    KEYRING_UNAVAILABLE = "KEYRING_UNAVAILABLE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    PROVIDER_SERVER_ERROR = "PROVIDER_SERVER_ERROR"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    OUTPUT_SCHEMA_INVALID = "OUTPUT_SCHEMA_INVALID"
    LOCAL_UNAVAILABLE = "LOCAL_UNAVAILABLE"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    MODEL_NOT_APPROVED = "MODEL_NOT_APPROVED"
    MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
    GPU_OOM = "GPU_OOM"
    RUNTIME_VERSION_MISMATCH = "RUNTIME_VERSION_MISMATCH"
    FALLBACK_NOT_ALLOWED = "FALLBACK_NOT_ALLOWED"
    RUNTIME_MODE_BLOCKED = "RUNTIME_MODE_BLOCKED"
    INVALID_ENDPOINT = "INVALID_ENDPOINT"
    INVALID_PROVIDER_RESPONSE = "INVALID_PROVIDER_RESPONSE"


@dataclass(frozen=True, slots=True)
class PromptReference:
    prompt_bundle_version: str
    prompt_id: str
    prompt_version: str
    content_hash: str
    agent_role: str
    subgraph_name: str
    node_name: str
    node_state: str
    purpose: str
    input_schema_version: str
    output_schema_version: str


@dataclass(frozen=True, slots=True)
class OutputSchemaDefinition:
    schema_version: str
    json_schema: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class RuntimePolicy:
    api_timeout_seconds: int = 120
    local_timeout_seconds: int = 180
    structured_output_repair_budget: int = 1
    max_fallback_count: int = 1
    # docs/15 section 9.5 (Runtime Prompt Activation Gate): fixed sampling
    # conditions for the Node Prompt Gate only -- never set by production
    # callers (see launcher/dev.py, which always constructs RuntimePolicy()
    # with no args). None means "use the provider's own default", which is
    # what every production dispatch path does today. Fixing these values
    # narrows sampling variance on a best-effort basis; it does not
    # guarantee bit-identical, fully deterministic output.
    sampling_temperature: float | None = None
    sampling_seed: int | None = None


@dataclass(frozen=True, slots=True)
class StructuredLLMResult:
    structured_output: object
    provider: str
    model: str
    requested_mode: RequestedRuntimeMode
    actual_runtime: ActualRuntime
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    latency_ms: int
    estimated_cost_usd: float | None
    fallback_reason: str | None
    structured_output_attempts: int
    provider_request_id: str | None
    safe_error_code: str | None
    provider_calls_consumed: int = 1


@dataclass(frozen=True, slots=True)
class ProviderResponsePayload:
    content: object
    model: str
    provider_request_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    estimated_cost_usd: float | None = None


@dataclass(frozen=True, slots=True)
class HardwareCapability:
    cpu_arch: str
    core_summary: str
    memory_bytes: int | None
    gpu_present: bool
    gpu_vendor: str | None
    gpu_name: str | None
    gpu_memory_bytes: int | None
    capability_status: HardwareCapabilityStatus
    safe_reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProbeResult:
    availability: AvailabilityState
    safe_error_code: str | None = None
    detail: str | None = None
    last_probe_at_ms: int | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ApprovedModelInfo:
    model_id: str
    runtime: str
    manifest_version: str
    schema_version: str
    minimum_runtime_version: str | None = None
    model_family: str | None = None
    capability_profile_id: str | None = None
    digest: str | None = None


@dataclass(frozen=True, slots=True)
class RouteDecisionInput:
    build_profile: str
    requested_mode: RequestedRuntimeMode
    external_llm_consent: bool
    api_credential_state: LLMCredentialState
    api_probe: ProbeResult
    hardware_capability: HardwareCapability
    ollama_probe: ProbeResult
    approved_model: ApprovedModelInfo | None


@dataclass(frozen=True, slots=True)
class RouteDecision:
    primary_runtime: ActualRuntime
    fallback_allowed: bool
    fallback_target: ActualRuntime | None
    safe_reason_code: str | None


class LLMInvocationError(RuntimeError):
    """Typed failure returned by provider and routing layers."""

    def __init__(
        self,
        code: LLMErrorCode,
        message: str,
        *,
        retryable: bool = False,
        fallback_reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.fallback_reason = fallback_reason


class StructuredLLMProvider(Protocol):
    """Provider that can produce structured JSON output."""

    provider_name: str
    runtime: ActualRuntime

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        runtime_policy: RuntimePolicy,
        api_key: str | None,
    ) -> ProviderResponsePayload:
        """Return one provider payload for structured parsing."""


class SchemaRepairer(Protocol):
    """Optional repair boundary for one invalid structured payload."""

    def repair(
        self,
        *,
        prompt_ref: PromptReference,
        failed_output: object,
        output_schema: OutputSchemaDefinition,
        attempt_no: int,
        failure_reason_code: str,
    ) -> object:
        """Return one repaired candidate output."""


class HardwareProbe(Protocol):
    def probe(self) -> HardwareCapability:
        """Return hardware capability metadata without touching user secrets."""


class OllamaRuntimeProbe(Protocol):
    def probe(
        self,
        *,
        endpoint: str | None,
        approved_model: ApprovedModelInfo | None,
    ) -> ProbeResult:
        """Return loopback-only Ollama availability information."""


class LLMRuntimeRouter(Protocol):
    def decide(self, request: RouteDecisionInput) -> RouteDecision:
        """Choose one primary runtime and fallback policy."""
