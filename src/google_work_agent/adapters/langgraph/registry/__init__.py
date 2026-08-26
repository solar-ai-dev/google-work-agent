"""Canonical LangGraph node and safe-resume registries."""

from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)

__all__ = ["NodeRegistry", "ResumeTargetRegistry"]
