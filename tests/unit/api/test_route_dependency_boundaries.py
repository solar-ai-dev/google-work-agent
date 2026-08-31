from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType
from typing import Any, get_args, get_type_hints

import google_work_agent.api.routes as route_package
from google_work_agent.api.container import ApiContainer
from google_work_agent.api.dependencies.actions import ActionRouteDependencies
from google_work_agent.api.dependencies.attachments import AttachmentRouteDependencies
from google_work_agent.api.dependencies.conversations import ConversationRouteDependencies
from google_work_agent.api.dependencies.google_connections import GoogleRouteDependencies
from google_work_agent.api.dependencies.health_checks import HealthRouteDependencies
from google_work_agent.api.dependencies.identities import IdentityRouteDependencies
from google_work_agent.api.dependencies.llm_connections import LLMRouteDependencies
from google_work_agent.api.dependencies.resources import ResourceRouteDependencies
from google_work_agent.api.dependencies.runs import RunEventRouteDependencies, RunRouteDependencies
from google_work_agent.api.dependencies.runtime_summaries import RuntimeRouteDependencies
from google_work_agent.api.dependencies.sessions import SessionRouteDependencies
from google_work_agent.api.dependencies.settings import SettingsRouteDependencies

ROUTE_DEPENDENCY_TYPES = (
    ActionRouteDependencies,
    AttachmentRouteDependencies,
    ConversationRouteDependencies,
    GoogleRouteDependencies,
    HealthRouteDependencies,
    IdentityRouteDependencies,
    LLMRouteDependencies,
    ResourceRouteDependencies,
    RunRouteDependencies,
    RunEventRouteDependencies,
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
        assert "get_api_container" not in vars(module), module.__name__
        assert not any(
            _origin_module_name(value).startswith(
                ("google_work_agent.adapters.", "google_work_agent.persistence.")
            )
            for value in imported_values
        ), module.__name__


def test_route_dependency_contracts_are_owner_local_and_do_not_expose_any() -> None:
    for dependency_type in ROUTE_DEPENDENCY_TYPES:
        assert dependency_type.__module__.startswith("google_work_agent.api.dependencies.")
        assert dependency_type.__module__ != "google_work_agent.api.dependencies"
        assert not any(
            _contains_any(annotation) for annotation in get_type_hints(dependency_type).values()
        ), dependency_type.__name__
