from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType
from typing import Any, get_args, get_type_hints

from google_work_agent.api import route_dependencies
from google_work_agent.api import routes as route_package
from google_work_agent.api.container import ApiContainer
from google_work_agent.api.route_dependencies import (
    ActionRouteDependencies,
    AttachmentRouteDependencies,
    ConversationRouteDependencies,
    EventRouteDependencies,
    GoogleRouteDependencies,
    HealthRouteDependencies,
    IdentityRouteDependencies,
    LLMRouteDependencies,
    ResourceRouteDependencies,
    RunRouteDependencies,
    RuntimeRouteDependencies,
    SessionRouteDependencies,
    SettingsRouteDependencies,
)

ROUTE_DEPENDENCY_TYPES = (
    ActionRouteDependencies,
    AttachmentRouteDependencies,
    ConversationRouteDependencies,
    EventRouteDependencies,
    GoogleRouteDependencies,
    HealthRouteDependencies,
    IdentityRouteDependencies,
    LLMRouteDependencies,
    ResourceRouteDependencies,
    RunRouteDependencies,
    RuntimeRouteDependencies,
    SessionRouteDependencies,
    SettingsRouteDependencies,
)


def _route_modules() -> tuple[ModuleType, ...]:
    names = (
        module_info.name
        for module_info in pkgutil.iter_modules(
            route_package.__path__,
            prefix=f"{route_package.__name__}.",
        )
    )
    return tuple(importlib.import_module(name) for name in names)


def _origin_module_name(value: object) -> str:
    if isinstance(value, ModuleType):
        return value.__name__
    return str(getattr(value, "__module__", ""))


def _contains_any(annotation: object) -> bool:
    return annotation is Any or any(_contains_any(arg) for arg in get_args(annotation))


def test_route_modules_do_not_import_container_or_concrete_infrastructure() -> None:
    for module in _route_modules():
        imported_values = tuple(vars(module).values())

        assert ApiContainer not in imported_values, module.__name__
        assert "get_container" not in vars(module), module.__name__
        assert not any(
            _origin_module_name(value).startswith(
                ("google_work_agent.adapters.", "google_work_agent.persistence.")
            )
            for value in imported_values
        ), module.__name__


def test_route_dependency_contracts_do_not_expose_any() -> None:
    declared_dependency_types = {
        value
        for value in vars(route_dependencies).values()
        if isinstance(value, type) and value.__module__ == route_dependencies.__name__
    }

    assert set(ROUTE_DEPENDENCY_TYPES).issubset(declared_dependency_types)
    for dependency_type in ROUTE_DEPENDENCY_TYPES:
        assert not any(
            _contains_any(annotation) for annotation in get_type_hints(dependency_type).values()
        ), dependency_type.__name__
