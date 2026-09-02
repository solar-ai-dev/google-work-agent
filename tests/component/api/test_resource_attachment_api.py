from __future__ import annotations

from base64 import urlsafe_b64encode
from collections.abc import Awaitable, Callable
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from google_work_agent.adapters.system.filesystem_attachment_staging import (
    FilesystemAttachmentStagingAdapter,
)
from google_work_agent.adapters.system.filesystem_operational_command_replay import (
    FilesystemOperationalCommandReplayAdapter,
)
from google_work_agent.api.dependencies.attachments import (
    AttachmentRouteDependencies,
    get_attachment_route_dependencies,
)
from google_work_agent.api.routes import attachments
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.attachment.create_staged_attachment import (
    CreateStagedAttachmentHandler,
)
from google_work_agent.application.use_cases.attachment.get_attachment import GetAttachmentHandler
from google_work_agent.ports.connector.connector_read_port import (
    ConnectorReadResultV1,
    JsonValue,
)
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)


class _AttachmentRead:
    def execute_read(
        self,
        _binding: ValidatedConnectorToolBindingV1,
        arguments: dict[str, JsonValue],
    ) -> ConnectorReadResultV1:
        data = b"download"
        return ConnectorReadResultV1(
            1,
            "gmail_get_attachment",
            "read-1",
            {
                "message_id": arguments["message_id"],
                "attachment_id": arguments["attachment_id"],
                "size_bytes": len(data),
                "sha256": sha256(data).hexdigest(),
                "data_base64url": urlsafe_b64encode(data).rstrip(b"=").decode("ascii"),
            },
            None,
            None,
        )


def _app(dependencies: AttachmentRouteDependencies) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = "request-1"
        return await call_next(request)

    app.include_router(attachments.router)
    app.dependency_overrides[get_attachment_route_dependencies] = lambda: dependencies
    return app


def test_attachment_multipart__replay_and__safe_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(attachments, "enforce_access", lambda *_args, **_kwargs: None)
    staging_dir = tmp_path / "staging"
    dependencies = AttachmentRouteDependencies(
        api_contract_version="1",
        get_attachment_handler=GetAttachmentHandler(
            connector_read=_AttachmentRead(),
            tool_registry=load_signed_tool_registry(),
        ),
        create_staged_attachment_handler=CreateStagedAttachmentHandler(
            staging=FilesystemAttachmentStagingAdapter(staging_dir=staging_dir),
            replay=FilesystemOperationalCommandReplayAdapter(tmp_path / "replay"),
        ),
        max_attachment_bytes=1024,
    )
    headers = {"X-Api-Contract-Version": "1"}

    with TestClient(_app(dependencies)) as client:
        first = client.post(
            "/api/v1/attachments/stage",
            data={"command_id": "stage-command-1"},
            files={"file": ("note.txt", b"attachment", "text/plain")},
            headers=headers,
        )
        second = client.post(
            "/api/v1/attachments/stage",
            data={"command_id": "stage-command-1"},
            files={"file": ("note.txt", b"attachment", "text/plain")},
            headers=headers,
        )
        download = client.get(
            "/api/v1/gmail/messages/message-1/attachments/attachment-1",
            headers=headers,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["staged_attachment_id"] == first.json()["staged_attachment_id"]
    assert len(tuple(staging_dir.glob("*.bin"))) == 1
    assert download.content == b"download"
    assert download.headers["content-length"] == str(len(b"download"))
    assert download.headers["content-disposition"] == 'attachment; filename="attachment"'
    assert download.headers["x-content-type-options"] == "nosniff"
