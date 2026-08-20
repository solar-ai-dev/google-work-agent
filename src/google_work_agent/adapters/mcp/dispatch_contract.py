"""Final client-side MCP dispatch contract guard.

This wrapper complements ``ManifestEnforcedMCPTransport`` rather than replacing
it. Immediately before every tool call it proves that the verified manifest
bytes have not changed and validates the exact connector input schema. The
inner manifest guard then performs membership/negotiated-version checks right
before delegate dispatch. Responses are validated against the same schema
authority before crossing into gateway code.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from google_work_agent.adapters.mcp.manifest_guard import ManifestEnforcedMCPTransport
from google_work_agent.adapters.mcp.transport import MCPConnectorDescriptor
from google_work_agent.domain.enums import EffectType
from google_work_agent.domain.google_workspace_tool_contracts import (
    ToolContractViolation,
    validate_tool_input,
    validate_tool_output,
)
from google_work_agent.ports import (
    DeliveryCertainty,
    MCPControlResponse,
    MCPRuntimeMetadata,
    MCPToolResponse,
    MCPTransportError,
    MCPTransportErrorCode,
)


class DispatchContractMCPTransport:
    """Apply immutable-artifact and schema checks around one manifest guard."""

    def __init__(
        self,
        *,
        delegate: ManifestEnforcedMCPTransport,
        descriptor: MCPConnectorDescriptor,
    ) -> None:
        self._delegate = delegate
        self._descriptor = descriptor

    def call_tool(self, *, tool_name: str, arguments: dict[str, object]) -> MCPToolResponse:
        self._assert_manifest_bytes_unchanged()
        try:
            validate_tool_input(tool_name, arguments)
        except (KeyError, ToolContractViolation) as error:
            raise MCPTransportError(
                code=MCPTransportErrorCode.TOOL_REJECTED,
                message="INVALID_ARGUMENT",
                delivery_certainty=DeliveryCertainty.NOT_SENT,
                dispatch_started=False,
            ) from error

        response = self._delegate.call_tool(tool_name=tool_name, arguments=arguments)
        try:
            validate_tool_output(tool_name, response.payload)
        except (KeyError, ToolContractViolation) as error:
            raise MCPTransportError(
                code=MCPTransportErrorCode.SCHEMA_MISMATCH,
                message="INVALID_MCP_OUTPUT",
                delivery_certainty=self._output_failure_certainty(tool_name),
                request_id=response.request_id,
            ) from error
        return response

    def call_control(
        self,
        *,
        method: str,
        arguments: dict[str, object],
    ) -> MCPControlResponse:
        return self._delegate.call_control(method=method, arguments=arguments)

    def runtime_metadata(self) -> MCPRuntimeMetadata:
        return self._delegate.runtime_metadata()

    def close(self) -> None:
        self._delegate.close()

    def restart(self) -> MCPRuntimeMetadata:
        return self._delegate.restart()

    @property
    def service_instance_id(self) -> str:
        return self._delegate.service_instance_id

    @property
    def process_instance_id(self) -> str | None:
        return self._delegate.process_instance_id

    def sign_claim_context(self, payload: dict[str, object]) -> str:
        return self._delegate.sign_claim_context(payload)

    def _assert_manifest_bytes_unchanged(self) -> None:
        path = Path(self._descriptor.artifact_config.manifest_path)
        try:
            actual = sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise MCPTransportError(
                code=MCPTransportErrorCode.ARTIFACT_REJECTED,
                message="verified MCP manifest is unavailable before dispatch",
                delivery_certainty=DeliveryCertainty.NOT_SENT,
                dispatch_started=False,
            ) from error
        if actual != self._descriptor.artifact_config.expected_manifest_sha256:
            raise MCPTransportError(
                code=MCPTransportErrorCode.ARTIFACT_REJECTED,
                message="verified MCP manifest changed before dispatch",
                delivery_certainty=DeliveryCertainty.NOT_SENT,
                dispatch_started=False,
            )

    def _output_failure_certainty(self, tool_name: str) -> DeliveryCertainty:
        entry = self._descriptor.expected_tool_registry.get(tool_name)
        if entry is None or entry.effect_type is EffectType.READ:
            return DeliveryCertainty.MAY_HAVE_BEEN_SENT
        return DeliveryCertainty.SENT_RESPONSE_LOST
