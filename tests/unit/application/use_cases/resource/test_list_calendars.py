"""Exact ownership smoke gate for the canonical Application module."""

from collections.abc import Callable, Iterator

import pytest

from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.resource.list_calendars import (
    ListCalendarsHandler,
    ListCalendarsQuery,
)
from google_work_agent.application.use_cases.resource.opaque_continuation_access import (
    LocalResourceContinuationStore,
)
from google_work_agent.ports.connector.connector_failure import ConnectorOperationFailure
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1, JsonValue
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)


class _CalendarListRead:
    def __init__(self) -> None:
        self.page_tokens: list[str | None] = []

    def execute_read(
        self,
        _binding: ValidatedConnectorToolBindingV1,
        tool_arguments: dict[str, JsonValue],
    ) -> ConnectorReadResultV1:
        page_token = tool_arguments["page_token"]
        self.page_tokens.append(None if page_token is None else str(page_token))
        return ConnectorReadResultV1(
            1,
            "calendar_list_calendars",
            "read-1",
            {
                "items": [
                    {
                        "resource_id": "primary",
                        "payload": {"summary": "Primary calendar", "primary": True},
                    }
                ]
            },
            "provider-secret" if page_token is None else None,
            None,
        )


def _tokens(values: Iterator[str]) -> Callable[[], str]:
    return lambda: next(values)


def test_calendar_list__continuation_is_local__and_principal_bound() -> None:
    read = _CalendarListRead()
    handler = ListCalendarsHandler(
        connector_read=read,
        registry=load_signed_tool_registry(),
        continuation_store=LocalResourceContinuationStore(
            token_factory=_tokens(iter(("local-calendars",)))
        ),
    )
    first = handler(ListCalendarsQuery("a" * 64, "account-1"))
    second = handler(ListCalendarsQuery("a" * 64, "account-1", first.next_page_token))

    assert first.next_page_token == "local-calendars"
    assert first.items[0].calendar_id == "primary"
    assert first.items[0].primary is True
    assert first.next_page_token != "provider-secret"
    assert second.next_page_token is None
    assert read.page_tokens == [None, "provider-secret"]

    with pytest.raises(ConnectorOperationFailure):
        handler(ListCalendarsQuery("b" * 64, "account-1", first.next_page_token))
