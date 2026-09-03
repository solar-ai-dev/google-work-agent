from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import (
    sqlite_unit_of_work_factory,
)
from google_work_agent.api.dependencies.conversations import (
    ConversationRouteDependencies,
    get_conversation_route_dependencies,
)
from google_work_agent.api.routes import conversations as conversation_routes
from google_work_agent.application.use_cases.conversation.create_conversation import (
    CreateConversationHandler,
)
from google_work_agent.application.use_cases.conversation.get_conversation_history import (
    GetConversationHistoryHandler,
)
from google_work_agent.application.use_cases.conversation.list_conversations import (
    ListConversationsHandler,
)


def test_conversation_route__uses_application_handlers__and_matches_frontend_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "api-application-wiring.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('account-1', 'u@example.com', NULL, 1, NULL);"
        )
        connection.commit()

    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    dependencies = ConversationRouteDependencies(
        api_contract_version="1",
        unit_of_work_factory=factory,
        create_conversation_handler=CreateConversationHandler(
            unit_of_work_factory=factory,
            now_ms=lambda: 10,
        ),
        list_conversations_handler=ListConversationsHandler(unit_of_work_factory=factory),
        get_conversation_history_handler=GetConversationHistoryHandler(
            unit_of_work_factory=factory
        ),
        current_account_id=lambda: "account-1",
        new_id=lambda: "conversation-1",
    )
    app = FastAPI()

    @app.middleware("http")
    async def add_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = "request-1"
        return await call_next(request)

    app.include_router(conversation_routes.router)
    app.dependency_overrides[get_conversation_route_dependencies] = lambda: dependencies
    monkeypatch.setattr(conversation_routes, "enforce_access", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        conversation_routes,
        "enforce_runtime_operation",
        lambda *_args, **_kwargs: None,
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/conversations",
            json={"schema_version": 1, "command_id": "create-1", "title": "R2"},
        )
        listed = client.get("/api/v1/conversations?page_size=50")

    expected_item = {
        "schema_version": 1,
        "conversation_id": "conversation-1",
        "title": "R2",
        "latest_message_at_ms": None,
        "open_run_id": None,
    }
    assert created.status_code == 201
    assert created.json() == expected_item
    assert listed.status_code == 200
    assert listed.json() == {
        "schema_version": 1,
        "items": [expected_item],
        "next_cursor": None,
    }
    with connect_sqlite(database_path) as connection:
        facts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM conversations WHERE id='conversation-1'),
                (SELECT status FROM command_receipts WHERE command_id='create-1');
            """
        ).fetchone()
    assert tuple(facts) == (1, "APPLIED")
