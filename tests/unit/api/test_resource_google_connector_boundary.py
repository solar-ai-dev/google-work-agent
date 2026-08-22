from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ROUTE_DIR = ROOT / "src" / "google_work_agent" / "api" / "routes"


def _source(name: str) -> str:
    return (ROUTE_DIR / name).read_text(encoding="utf-8")


def test_resource_attachment_google_routes_hide_concrete_connector_exceptions() -> None:
    forbidden = (
        "GoogleWorkspaceGatewayError",
        "GoogleWorkspaceErrorCode",
        "MCPTransportError",
        "MCPTransportErrorCode",
        "AttachmentStagingError",
    )
    for route_name in ("resources.py", "attachments.py", "google.py"):
        source = _source(route_name)
        for symbol in forbidden:
            assert symbol not in source, (route_name, symbol)


def test_routes_call_canonical_application_handlers() -> None:
    resources = _source("resources.py")
    attachments = _source("attachments.py")
    google = _source("google.py")

    assert "ListResourcesHandler" in resources
    assert "CountResourcesHandler" in resources
    assert "GetResourceHandler" in resources
    assert "FetchAttachmentHandler" in attachments
    assert "StageAttachmentHandler" in attachments
    assert "StartOAuthHandler" in google
    assert "GetConnectionHandler" in google
    assert "DisconnectConnectorHandler" in google


def test_route_wire_ownership_keeps_attachment_base64_decode_in_api() -> None:
    attachments = _source("attachments.py")
    assert "base64.b64decode" in attachments
