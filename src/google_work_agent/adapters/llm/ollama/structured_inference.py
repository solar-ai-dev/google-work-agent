"""Canonical Ollama structured-inference leaf."""

from google_work_agent.adapters.llm.ollama.transport import (
    _OllamaStructuredInferenceMechanics,
)


class OllamaStructuredInferenceAdapter(_OllamaStructuredInferenceMechanics):
    """The sole public local structured-inference provider leaf."""


__all__ = ["OllamaStructuredInferenceAdapter"]
