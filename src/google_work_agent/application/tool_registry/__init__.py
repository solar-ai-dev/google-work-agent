"""Application-owned Signed Tool Registry authority."""

from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry

__all__ = ["SignedToolRegistry", "load_signed_tool_registry"]
