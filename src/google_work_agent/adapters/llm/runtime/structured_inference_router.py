"""Canonical API structured-inference runtime binding."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from google_work_agent.adapters.llm.api_provider import APIProviderTransport
from google_work_agent.adapters.llm.api_provider import (
    ApiStructuredLLMProvider as ApiStructuredInferenceLeaf,
)
from google_work_agent.adapters.llm.prompt_input_guard import PromptInputGuardedProvider
from google_work_agent.application.orchestration.prompt_input_contract import (
    PromptRuntimeInputContractValidator,
)
from google_work_agent.application.orchestration.prompt_registry import default_prompt_manifest_path
from google_work_agent.ports import ActualRuntime, PromptReference


def _no_instruction_text(prompt_ref: PromptReference) -> str:
    del prompt_ref
    return ""


class StructuredInferenceRuntimeRouter(PromptInputGuardedProvider):
    """Production API inference binding with mandatory prompt input validation."""

    __slots__ = ()

    def __init__(
        self,
        *,
        provider_name: str,
        transport: APIProviderTransport,
        model: str,
        runtime: ActualRuntime = ActualRuntime.API_LLM,
        resolve_instruction_text: Callable[[PromptReference], str] = _no_instruction_text,
        prompt_manifest_path: Path | None = None,
    ) -> None:
        manifest_path = prompt_manifest_path or default_prompt_manifest_path()
        super().__init__(
            delegate=ApiStructuredInferenceLeaf(
                provider_name=provider_name,
                transport=transport,
                model=model,
                runtime=runtime,
                resolve_instruction_text=resolve_instruction_text,
            ),
            validator=PromptRuntimeInputContractValidator(manifest_path=manifest_path),
        )
