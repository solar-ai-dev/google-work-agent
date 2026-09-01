import pytest

from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)


def _binding(**overrides: object) -> ValidatedConnectorToolBindingV1:
    values: dict[str, object] = {
        "schema_version": 1,
        "connector_id": "google_workspace",
        "resource_type": "gmail_thread",
        "tool_id": "gmail_get_thread",
        "effect": "READ",
        "input_schema_ref": "v1",
        "output_schema_ref": "v1",
        "registry_entry_hash": "a" * 64,
    }
    values.update(overrides)
    return ValidatedConnectorToolBindingV1(**values)  # type: ignore[arg-type]


def test_validated_binding_accepts_exact_contract() -> None:
    assert _binding().tool_id == "gmail_get_thread"


@pytest.mark.parametrize(
    ("field", "value"),
    [("effect", "EXECUTE"), ("registry_entry_hash", "A" * 64), ("tool_id", "")],
)
def test_validated_binding_rejects_invalid_contract(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        _binding(**{field: value})
