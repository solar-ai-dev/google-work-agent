from __future__ import annotations

import pytest

from google_work_agent.adapters.connectors.connector_not_registered_error import (
    ConnectorNotRegisteredError,
)
from google_work_agent.adapters.connectors.connector_registry import ConnectorRegistry


def test_registry_resolves_only_explicit_connector_id() -> None:
    google = object()
    github = object()
    registry = ConnectorRegistry({"google_workspace": google, "github": github})

    assert registry.registered_connector_ids == ("github", "google_workspace")
    assert registry.resolve("github") is github
    assert registry.resolve("google_workspace") is google


def test_registry_has_no_default_provider_fallback() -> None:
    google = object()
    registry = ConnectorRegistry({"google_workspace": google})

    with pytest.raises(
        ConnectorNotRegisteredError,
        match="connector backend not registered: github",
    ):
        registry.resolve("github")


def test_registry_rejects_empty_authority() -> None:
    with pytest.raises(ValueError, match="requires at least one backend"):
        ConnectorRegistry({})


def test_registry_rejects_blank_connector_id() -> None:
    with pytest.raises(ValueError, match="ids must be non-empty"):
        ConnectorRegistry({"": object()})
