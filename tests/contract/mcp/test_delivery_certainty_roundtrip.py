from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from google_work_agent.adapters.connectors import build_google_workspace_connector_descriptor
from google_work_agent.adapters.mcp import (
    MCPArtifactConfig,
    build_manifest_payload,
    calculate_file_sha256,
)
from google_work_agent.adapters.mcp.delivery_gateway import _delivery_aware_google_error
from google_work_agent.adapters.mcp.delivery_transport import DeliveryAwareSubprocessMCPTransport
from google_work_agent.ports import (
    DeliveryCertainty,
    MCPTransportError,
)


@pytest.mark.parametrize(
    "certainty",
    [
        DeliveryCertainty.NOT_SENT,
        DeliveryCertainty.MAY_HAVE_BEEN_SENT,
        DeliveryCertainty.SENT_RESPONSE_LOST,
    ],
)
def test_delivery_certainty_roundtrips_server_transport_gateway(
    tmp_path: Path,
    certainty: DeliveryCertainty,
) -> None:
    manifest_path = tmp_path / "mcp-manifest.json"
    manifest_path.write_text(
        json.dumps(build_manifest_payload(), sort_keys=True),
        encoding="utf-8",
    )
    executable = Path(sys.executable).resolve()
    descriptor = build_google_workspace_connector_descriptor(
        MCPArtifactConfig(
            executable_path=str(executable),
            manifest_path=str(manifest_path.resolve()),
            expected_binary_sha256=calculate_file_sha256(executable),
            expected_manifest_sha256=calculate_file_sha256(manifest_path),
            expected_manifest_version="2026-08-07.p0",
            expected_protocol_version="2026-08-07.p0",
            expected_tool_registry_version="2026-08-06.p0",
            startup_timeout_ms=5_000,
            request_timeout_ms=5_000,
            max_restart_count=1,
            environment="DEVELOPMENT",
            service_instance_id="svc-delivery-contract",
            working_directory=str(Path(__file__).resolve().parents[3]),
            module_name="tests.fakes.mcp_server",
        )
    )
    transport = DeliveryAwareSubprocessMCPTransport(descriptor=descriptor)
    try:
        with pytest.raises(MCPTransportError) as captured:
            transport.call_tool(
                tool_name="gmail_get_thread",
                arguments={"__test_delivery_certainty": certainty.value},
            )
    finally:
        transport.close()

    assert captured.value.delivery_certainty is certainty
    mapped = _delivery_aware_google_error(captured.value)
    assert mapped.delivery_certainty is certainty
    assert mapped.delivered is (certainty is not DeliveryCertainty.NOT_SENT)
    assert mapped.mutated is (certainty is DeliveryCertainty.SENT_RESPONSE_LOST)


def test_legacy_dispatch_started_fallback_remains_conservative() -> None:
    error = MCPTransportError(
        code=captured_code(),
        message="legacy",
        dispatch_started=True,
    )

    assert error.delivery_certainty is DeliveryCertainty.MAY_HAVE_BEEN_SENT


def captured_code():  # type: ignore[no-untyped-def]
    from google_work_agent.ports import MCPTransportErrorCode

    return MCPTransportErrorCode.TIMEOUT
