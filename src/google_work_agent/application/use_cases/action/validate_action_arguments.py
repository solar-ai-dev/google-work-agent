"""Validate Action arguments against only the current registered Tool schema."""

from dataclasses import dataclass

from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


@dataclass(frozen=True, slots=True)
class ValidateActionArgumentsQueryV1:
    arguments: dict[str, object]
    input_schema: dict[str, object]


@dataclass(frozen=True, slots=True)
class ActionArgumentsSchemaValidationResultV1:
    valid: bool
    normalized_arguments: dict[str, object]
    error_paths: tuple[str, ...]


class ValidateActionArgumentsHandler:
    def __call__(
        self, query: ValidateActionArgumentsQueryV1
    ) -> ActionArgumentsSchemaValidationResultV1:
        errors = tuple(validate_output_schema(query.arguments, query.input_schema))
        return ActionArgumentsSchemaValidationResultV1(
            valid=not errors,
            normalized_arguments=dict(query.arguments),
            error_paths=errors,
        )


__all__ = [
    "ActionArgumentsSchemaValidationResultV1",
    "ValidateActionArgumentsHandler",
    "ValidateActionArgumentsQueryV1",
]
