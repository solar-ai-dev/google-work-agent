"""Prompt selection, failure, and provider-result contracts."""

from typing import Literal, Required, TypedDict


class PromptSelectionKey(TypedDict):
    """Prompt selection key fields defined by `docs/06-agent-workflow.md` section 7."""

    agent_role: str
    subgraph_name: str
    node_name: str
    node_state: str
    purpose: str
    input_schema_version: str
    output_schema_version: str


class PromptRef(TypedDict):
    """Prompt reference fields defined by `docs/06-agent-workflow.md` section 7."""

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


class AgentFailureRecordV1(TypedDict):
    """Invocation-local failure scratch owned by one native agent subgraph."""

    schema_version: Required[Literal[1]]
    reason_code: str
    diagnostic: str | None
    retryable: bool


class AgentDispositionV1(TypedDict):
    """Invocation-local disposition returned by one native agent subgraph."""

    schema_version: Required[Literal[1]]
    status: str
    next_target: str | None
    reason_code: str | None


class _LlmProviderResultRequired(TypedDict):
    structured_output: dict[str, object]
    provider: str
    model: str
    actual_runtime: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


class LlmProviderResult(_LlmProviderResultRequired, total=False):
    """LLM provider result metadata from `docs/07-tool-mcp-internal-interface.md` section 18."""

    fallback_reason: str


PROMPT_SELECTION_KEY_FIELDS = frozenset(PromptSelectionKey.__annotations__)


PROMPT_REF_FIELDS = frozenset(PromptRef.__annotations__)


LLM_PROVIDER_RESULT_FIELDS = frozenset(LlmProviderResult.__annotations__)


LLM_PROVIDER_RESULT_REQUIRED_FIELDS = frozenset(LlmProviderResult.__required_keys__)


LLM_PROVIDER_RESULT_OPTIONAL_FIELDS = frozenset(LlmProviderResult.__optional_keys__)
