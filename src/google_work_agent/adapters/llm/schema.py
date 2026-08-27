"""Compatibility import for the application-owned schema validator."""

from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

__all__ = ["validate_output_schema"]
