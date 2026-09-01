"""List calendar containers through ConnectorReadPort."""

from dataclasses import dataclass

from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.resource.opaque_continuation_access import (
    LocalResourceContinuationStore,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
    normalize_google_workspace_failure,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadPort, JsonValue
from google_work_agent.ports.connector.contracts.google_workspace import GoogleWorkspaceGatewayError


@dataclass(frozen=True, slots=True)
class ListCalendarsQuery:
    session_digest: str
    account_id: str
    page_token: str | None = None
    page_size: int = 50

    def __post_init__(self) -> None:
        if (
            len(self.session_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.session_digest)
            or not self.account_id
        ):
            raise ValueError("resource continuation principal is invalid")


@dataclass(frozen=True, slots=True)
class CalendarContainerItem:
    schema_version: int
    calendar_id: str
    title: str
    primary: bool


@dataclass(frozen=True, slots=True)
class ListCalendarsResult:
    schema_version: int
    items: tuple[CalendarContainerItem, ...]
    next_page_token: str | None


class ListCalendarsHandler:
    def __init__(
        self,
        *,
        connector_read: ConnectorReadPort,
        registry: SignedToolRegistry,
        continuation_store: LocalResourceContinuationStore,
    ) -> None:
        self._connector_read = connector_read
        self._registry = registry
        self._continuation_store = continuation_store

    def __call__(self, query: ListCalendarsQuery) -> ListCalendarsResult:
        if not 1 <= query.page_size <= 100:
            raise ValueError("page_size must be in 1..100")
        scope = (query.session_digest, query.account_id, "calendars", str(query.page_size))
        try:
            provider_page_token = (
                None
                if query.page_token is None
                else self._continuation_store.resolve(scope=scope, local_handle=query.page_token)
            )
        except GoogleWorkspaceGatewayError as error:
            raise normalize_google_workspace_failure(error) from error
        result = self._connector_read.execute_read(
            self._registry.bind_required("google_workspace", "calendar_list_calendars", "READ"),
            {"page_token": provider_page_token, "page_size": query.page_size},
        )
        raw = result.output.get("items", [])
        if not isinstance(raw, list):
            raise _malformed_response()
        items = tuple(_calendar_item(item) for item in raw)
        next_page_token = (
            None
            if result.next_page_token is None
            else self._continuation_store.issue(
                scope=scope,
                provider_page_token=result.next_page_token,
            )
        )
        return ListCalendarsResult(1, items, next_page_token)


def _calendar_item(value: JsonValue) -> CalendarContainerItem:
    if not isinstance(value, dict):
        raise _malformed_response()
    resource_id = value.get("resource_id")
    payload = value.get("payload")
    if not isinstance(resource_id, str) or not resource_id or not isinstance(payload, dict):
        raise _malformed_response()
    title = payload.get("summary")
    primary = payload.get("primary", False)
    if not isinstance(title, str) or not title or not isinstance(primary, bool):
        raise _malformed_response()
    return CalendarContainerItem(1, resource_id, title, primary)


def _malformed_response() -> ConnectorOperationFailure:
    return ConnectorOperationFailure(
        code=ConnectorFailureCode.MALFORMED_RESPONSE,
        detail_code="CONNECTOR_RESPONSE_MALFORMED",
    )


__all__ = [
    "CalendarContainerItem",
    "ListCalendarsResult",
    "ListCalendarsHandler",
    "ListCalendarsQuery",
]
