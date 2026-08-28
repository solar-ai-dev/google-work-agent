"""Subprocess-backed MCP stdio transport."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Literal, cast

from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.ports import (
    ArtifactSignatureDecision,
    ArtifactSignatureVerifier,
    DeliveryCertainty,
    MCPClientPortError,
    MCPClientPortErrorCode,
    MCPRuntimeMetadata,
)
from google_work_agent.ports.connector.mcp_client_port import (
    JsonValue,
    MCPRestartResultV1,
    MCPToolCallResultV1,
    MCPToolDescriptorV1,
)

JsonObject = dict[str, object]
PROTOCOL_VERSION = "2026-08-07.p0"
MANIFEST_MESSAGE_LIMIT_BYTES = 64 * 1024
SESSION_KEY_BYTES = 32


class MCPProcessStatus(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    HANDSHAKING = "HANDSHAKING"
    VALIDATING_TOOLS = "VALIDATING_TOOLS"
    READY = "READY"
    DEGRADED = "DEGRADED"
    STOPPING = "STOPPING"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class MCPServerManifest:
    manifest_version: str
    protocol_version: str
    connector_id: str
    registry_manifest_hash: str
    tools: tuple[MCPToolDescriptorV1, ...]

    @classmethod
    def load(cls, path: Path) -> MCPServerManifest:
        raw = path.read_bytes()
        if len(raw) > MANIFEST_MESSAGE_LIMIT_BYTES:
            raise ValueError("MCP manifest exceeds size limit")
        decoded = json.loads(normalize_manifest_bytes(raw).decode("utf-8"))
        if not isinstance(decoded, dict) or set(decoded) != {
            "manifest_version",
            "protocol_version",
            "connector_id",
            "registry_manifest_hash",
            "tools",
        }:
            raise ValueError("MCP manifest field set mismatch")
        payload = cast(dict[str, object], decoded)
        raw_tools = payload.get("tools")
        if not isinstance(raw_tools, list) or not raw_tools:
            raise ValueError("MCP manifest tools must be a non-empty list")
        tools = tuple(
            _descriptor_from_payload(_require_json_object(item, "MCP tool descriptor"))
            for item in raw_tools
        )
        return cls(
            manifest_version=str(payload["manifest_version"]),
            protocol_version=str(payload["protocol_version"]),
            connector_id=str(payload["connector_id"]),
            registry_manifest_hash=str(payload["registry_manifest_hash"]),
            tools=tools,
        )


def build_manifest_payload_for_descriptors(
    *,
    connector_id: str,
    registry_manifest_hash: str,
    descriptors: tuple[MCPToolDescriptorV1, ...],
) -> dict[str, object]:
    return {
        "manifest_version": "2026-08-07.p0",
        "protocol_version": PROTOCOL_VERSION,
        "connector_id": connector_id,
        "registry_manifest_hash": registry_manifest_hash,
        "tools": [
            {
                "schema_version": descriptor.schema_version,
                "connector_id": descriptor.connector_id,
                "tool_id": descriptor.tool_id,
                "input_schema_ref": descriptor.input_schema_ref,
                "output_schema_ref": descriptor.output_schema_ref,
                "registry_entry_hash": descriptor.registry_entry_hash,
            }
            for descriptor in descriptors
        ],
    }


def _descriptor_from_payload(payload: dict[str, object]) -> MCPToolDescriptorV1:
    if set(payload) != {
        "schema_version",
        "connector_id",
        "tool_id",
        "input_schema_ref",
        "output_schema_ref",
        "registry_entry_hash",
    }:
        raise ValueError("MCP tool descriptor field set mismatch")
    return MCPToolDescriptorV1(
        schema_version=cast(Any, payload["schema_version"]),
        connector_id=str(payload["connector_id"]),
        tool_id=str(payload["tool_id"]),
        input_schema_ref=str(payload["input_schema_ref"]),
        output_schema_ref=str(payload["output_schema_ref"]),
        registry_entry_hash=str(payload["registry_entry_hash"]),
    )


def _require_json_object(value: object, contract_name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{contract_name} must be an object")
    return cast(dict[str, object], value)


@dataclass(frozen=True, slots=True)
class MCPArtifactConfig:
    executable_path: str
    manifest_path: str
    expected_binary_sha256: str
    expected_manifest_sha256: str
    expected_manifest_version: str
    expected_protocol_version: str
    expected_registry_manifest_hash: str
    startup_timeout_ms: int
    request_timeout_ms: int
    max_restart_count: int
    environment: str
    service_instance_id: str
    module_name: str = (
        "google_work_agent.adapters.connectors.google.workspace.mcp_server.entrypoint"
    )
    working_directory: str | None = None
    environment_allowlist: tuple[str, ...] = ("SYSTEMROOT", "WINDIR", "PATH", "TMP", "TEMP")
    extra_environment: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class MCPConnectorDescriptor:
    connector_id: str
    artifact_config: MCPArtifactConfig
    expected_tool_descriptors: tuple[MCPToolDescriptorV1, ...]

    def __post_init__(self) -> None:
        if not self.connector_id.strip():
            raise ValueError("connector_id must not be blank")


def normalize_manifest_bytes(raw: bytes) -> bytes:
    return raw.replace(b"\r\n", b"\n")


def calculate_file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class StaticArtifactSignatureVerifier(ArtifactSignatureVerifier):
    decision: ArtifactSignatureDecision

    def verify(
        self,
        *,
        executable_path: str,
        expected_binary_sha256: str,
    ) -> ArtifactSignatureDecision:
        del executable_path, expected_binary_sha256
        return self.decision


class StdioMCPClientAdapter:
    """Strict stdio client for the local MCP child process."""

    def __init__(
        self,
        *,
        descriptor: MCPConnectorDescriptor,
        runtime_registry: ConnectorRuntimeRegistry,
        signature_verifier: ArtifactSignatureVerifier | None = None,
    ) -> None:
        self._descriptor = descriptor
        self._config = descriptor.artifact_config
        self._signature_verifier = signature_verifier
        self._manifest = self._validate_artifacts()
        self._process: subprocess.Popen[str] | None = None
        self._stdout_queue: Queue[JsonObject] = Queue()
        self._stderr_lines: list[str] = []
        self._request_counter = 0
        self._restart_count = 0
        self._status = MCPProcessStatus.STOPPED
        self._last_safe_error_code: str | None = None
        self._process_instance_id: str | None = None
        self._session_key = secrets.token_hex(SESSION_KEY_BYTES)
        self._lock = threading.RLock()
        self._start_process()
        self._runtime_registry = runtime_registry
        runtime_registry.register(descriptor.connector_id, _BoundStdioRuntime(self))

    def list_tools(self, connector_id: str) -> list[MCPToolDescriptorV1]:
        return self._runtime_registry.resolve(connector_id).list_tools()

    def call_tool(
        self,
        connector_id: str,
        tool_id: str,
        arguments: JsonValue,
        timeout_ms: int,
    ) -> MCPToolCallResultV1:
        return self._runtime_registry.resolve(connector_id).call_tool(
            tool_id, arguments, timeout_ms
        )

    def restart_once(self, connector_id: str) -> MCPRestartResultV1:
        return self._runtime_registry.resolve(connector_id).restart_once()

    def _list_tools(self) -> list[MCPToolDescriptorV1]:
        return list(self._manifest.tools)

    def _call_tool(
        self,
        tool_id: str,
        arguments: JsonValue,
        timeout_ms: int,
    ) -> MCPToolCallResultV1:
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        if not isinstance(arguments, dict):
            raise TypeError("MCP tool arguments must be an object")
        message_type = (
            "control_call"
            if tool_id.startswith(("google.oauth.", "google.connection."))
            else "tool_call"
        )
        body_key = "method" if message_type == "control_call" else "tool_name"
        try:
            _, payload = self._request(
                message_type=message_type,
                body={body_key: tool_id, "arguments": arguments},
                timeout_ms=timeout_ms,
            )
        except MCPClientPortError as error:
            status: Literal["ERROR", "TIMEOUT", "DISCONNECTED"] = (
                "TIMEOUT"
                if error.code is MCPClientPortErrorCode.TIMEOUT
                else "DISCONNECTED"
                if error.code
                in {
                    MCPClientPortErrorCode.CONNECTION_CLOSED,
                    MCPClientPortErrorCode.PROCESS_UNAVAILABLE,
                }
                else "ERROR"
            )
            return MCPToolCallResultV1(
                schema_version=1,
                tool_id=tool_id,
                transport_status=status,
                payload={
                    "request_id": error.request_id,
                    "delivery_certainty": error.delivery_certainty.value,
                },
                error_code=error.code.value,
            )
        return MCPToolCallResultV1(
            schema_version=1,
            tool_id=tool_id,
            transport_status="OK",
            payload=cast(JsonValue, payload),
            error_code=None,
        )

    def runtime_metadata(self) -> MCPRuntimeMetadata:
        return MCPRuntimeMetadata(
            process_status=self._status.value,
            protocol_version=self._manifest.protocol_version,
            manifest_version=self._manifest.manifest_version,
            tool_registry_version=self._manifest.registry_manifest_hash,
            available_tool_count=len(self._manifest.tools),
            last_safe_error_code=self._last_safe_error_code,
            restart_count=self._restart_count,
            process_instance_id=self._process_instance_id,
        )

    @property
    def service_instance_id(self) -> str:
        return self._config.service_instance_id

    @property
    def process_instance_id(self) -> str | None:
        return self._process_instance_id

    def sign_claim_context(self, payload: dict[str, object]) -> str:
        normalized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hmac.new(bytes.fromhex(self._session_key), normalized, hashlib.sha256).hexdigest()

    def close(self) -> None:
        self._status = MCPProcessStatus.STOPPING
        process = self._process
        if process is None:
            self._status = MCPProcessStatus.STOPPED
            return
        try:
            self._send_json({"type": "shutdown"})
            process.wait(timeout=max(1, self._config.startup_timeout_ms // 1000))
        except Exception:
            process.kill()
            process.wait(timeout=5)
        finally:
            self._process = None
            self._status = MCPProcessStatus.STOPPED

    def restart(self) -> MCPRuntimeMetadata:
        with self._lock:
            if self._restart_count >= self._config.max_restart_count:
                self._status = MCPProcessStatus.FAILED
                raise MCPClientPortError(
                    code=MCPClientPortErrorCode.PROCESS_UNAVAILABLE,
                    message="mcp restart limit exhausted",
                )
            self.close()
            self._restart_count += 1
            self._start_process()
            return self.runtime_metadata()

    def _restart_once(self) -> MCPRestartResultV1:
        try:
            self.restart()
        except MCPClientPortError as error:
            return MCPRestartResultV1(
                schema_version=1,
                restarted=False,
                reason_code=error.code.value,
            )
        return MCPRestartResultV1(schema_version=1, restarted=True, reason_code=None)

    def _validate_artifacts(self) -> MCPServerManifest:
        executable_path = Path(self._config.executable_path)
        manifest_path = Path(self._config.manifest_path)
        if not executable_path.is_absolute() or not manifest_path.is_absolute():
            raise MCPClientPortError(
                code=MCPClientPortErrorCode.ARTIFACT_REJECTED,
                message="artifact paths must be absolute",
            )
        if calculate_file_sha256(executable_path) != self._config.expected_binary_sha256:
            raise MCPClientPortError(
                code=MCPClientPortErrorCode.ARTIFACT_REJECTED,
                message="binary hash mismatch",
            )
        if calculate_file_sha256(manifest_path) != self._config.expected_manifest_sha256:
            raise MCPClientPortError(
                code=MCPClientPortErrorCode.ARTIFACT_REJECTED,
                message="manifest hash mismatch",
            )
        if self._config.environment.upper() == "PRODUCTION":
            if self._signature_verifier is None:
                raise MCPClientPortError(
                    code=MCPClientPortErrorCode.ARTIFACT_REJECTED,
                    message="production launch requires a signature verifier",
                )
            decision = self._signature_verifier.verify(
                executable_path=str(executable_path),
                expected_binary_sha256=self._config.expected_binary_sha256,
            )
            if not decision.allowed:
                raise MCPClientPortError(
                    code=MCPClientPortErrorCode.ARTIFACT_REJECTED,
                    message=decision.detail or "artifact signature rejected",
                )
        try:
            manifest = MCPServerManifest.load(manifest_path)
        except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
            raise MCPClientPortError(
                code=MCPClientPortErrorCode.SCHEMA_MISMATCH,
                message="MCP manifest is invalid",
            ) from error
        if manifest.manifest_version != self._config.expected_manifest_version:
            raise MCPClientPortError(
                code=MCPClientPortErrorCode.SCHEMA_MISMATCH,
                message="manifest version mismatch",
            )
        if manifest.protocol_version != self._config.expected_protocol_version:
            raise MCPClientPortError(
                code=MCPClientPortErrorCode.SCHEMA_MISMATCH,
                message="protocol version mismatch",
            )
        if manifest.connector_id != self._descriptor.connector_id:
            raise MCPClientPortError(
                code=MCPClientPortErrorCode.SCHEMA_MISMATCH,
                message="connector id mismatch",
            )
        if manifest.registry_manifest_hash != self._config.expected_registry_manifest_hash:
            raise MCPClientPortError(
                code=MCPClientPortErrorCode.SCHEMA_MISMATCH,
                message="registry manifest hash mismatch",
            )
        self._validate_manifest_tools(manifest)
        return manifest

    def _validate_manifest_tools(self, manifest: MCPServerManifest) -> None:
        expected = {
            descriptor.tool_id: descriptor
            for descriptor in self._descriptor.expected_tool_descriptors
        }
        actual = {descriptor.tool_id: descriptor for descriptor in manifest.tools}
        if len(actual) != len(manifest.tools) or actual != expected:
            raise MCPClientPortError(
                code=MCPClientPortErrorCode.TOOL_REJECTED,
                message="MCP descriptor projection mismatch",
            )

    def _start_process(self) -> None:
        self._status = MCPProcessStatus.STARTING
        env = self._build_child_environment()
        command = [self._config.executable_path, "-m", self._config.module_name]
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            cwd=self._config.working_directory or os.getcwd(),
            env=env,
        )
        self._process = process
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self._perform_handshake()

    def _perform_handshake(self) -> None:
        self._status = MCPProcessStatus.HANDSHAKING
        _, handshake = self._request(
            message_type="handshake",
            body={
                "service_instance_id": self._config.service_instance_id,
                "session_key": self._session_key,
                "protocol_version": PROTOCOL_VERSION,
            },
        )
        self._process_instance_id = str(handshake["process_instance_id"])
        _, initialize = self._request(
            message_type="initialize",
            body={
                "manifest_version": self._manifest.manifest_version,
                "registry_manifest_hash": self._manifest.registry_manifest_hash,
            },
        )
        self._status = MCPProcessStatus.VALIDATING_TOOLS
        remote_manifest_version = str(initialize["manifest_version"])
        remote_protocol = str(initialize["protocol_version"])
        if remote_manifest_version != self._manifest.manifest_version:
            raise MCPClientPortError(
                code=MCPClientPortErrorCode.HANDSHAKE_FAILED,
                message="remote manifest mismatch",
            )
        if remote_protocol != self._manifest.protocol_version:
            raise MCPClientPortError(
                code=MCPClientPortErrorCode.HANDSHAKE_FAILED,
                message="remote protocol mismatch",
            )
        _, remote_tools = self._request(message_type="list_tools", body={})
        tool_names = tuple(str(name) for name in cast(list[object], remote_tools["tool_names"]))
        if tool_names != tuple(sorted(tool.tool_id for tool in self._manifest.tools)):
            raise MCPClientPortError(
                code=MCPClientPortErrorCode.TOOL_REJECTED,
                message="remote tool list mismatch",
            )
        self._status = MCPProcessStatus.READY

    def _build_child_environment(self) -> dict[str, str]:
        child_env: dict[str, str] = {}
        for key in self._config.environment_allowlist:
            value = os.environ.get(key)
            if value is not None:
                child_env[key] = value
        working_directory = Path(self._config.working_directory or os.getcwd())
        source_path = str((working_directory / "src").resolve())
        existing_pythonpath = child_env.get("PYTHONPATH")
        child_env["PYTHONPATH"] = (
            source_path
            if not existing_pythonpath
            else os.pathsep.join((source_path, existing_pythonpath))
        )
        child_env["GWA_MCP_MANIFEST_PATH"] = self._config.manifest_path
        child_env["GWA_MCP_ENVIRONMENT"] = self._config.environment
        if self._config.extra_environment is not None:
            child_env.update(self._config.extra_environment)
        return child_env

    def _request(
        self,
        *,
        message_type: str,
        body: JsonObject,
        timeout_ms: int | None = None,
    ) -> tuple[str, JsonObject]:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                self._last_safe_error_code = MCPClientPortErrorCode.PROCESS_UNAVAILABLE.value
                if self._restart_count < self._config.max_restart_count:
                    self._restart_count += 1
                    self._start_process()
                    process = self._process
                else:
                    self._status = MCPProcessStatus.FAILED
                    raise MCPClientPortError(
                        code=MCPClientPortErrorCode.PROCESS_UNAVAILABLE,
                        message="mcp child process unavailable",
                    )
            # A fresh request_id per call (never reused across restarts or
            # retries) is the canonical MCP protocol correlation identifier:
            # the child echoes it back on every response, and it is what
            # ObservabilityContext.mcp_request_id should be populated from.
            self._request_counter += 1
            request_id = f"req-{self._request_counter}"
            self._send_json({"id": request_id, "type": message_type, **body}, request_id=request_id)
            try:
                payload = self._wait_for_response(
                    request_id=request_id,
                    timeout_ms=(
                        self._config.request_timeout_ms if timeout_ms is None else timeout_ms
                    ),
                )
            except MCPClientPortError as error:
                self._last_safe_error_code = error.code.value
                if (
                    error.code
                    in {
                        MCPClientPortErrorCode.CONNECTION_CLOSED,
                        MCPClientPortErrorCode.PROCESS_UNAVAILABLE,
                    }
                    and self._restart_count < self._config.max_restart_count
                ):
                    self._restart_count += 1
                    self._start_process()
                raise
            return request_id, payload

    def _send_json(self, payload: JsonObject, *, request_id: str | None = None) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise MCPClientPortError(
                code=MCPClientPortErrorCode.PROCESS_UNAVAILABLE,
                message="mcp child stdin unavailable",
                request_id=request_id,
            )
        line = json.dumps(payload, sort_keys=True)
        try:
            process.stdin.write(line + "\n")
            process.stdin.flush()
        except OSError as error:
            raise MCPClientPortError(
                code=MCPClientPortErrorCode.CONNECTION_CLOSED,
                message="mcp child stdin closed during dispatch",
                dispatch_started=True,
                request_id=request_id,
            ) from error

    def _wait_for_response(self, *, request_id: str, timeout_ms: int) -> JsonObject:
        deadline = time.monotonic() + (timeout_ms / 1000)
        while time.monotonic() < deadline:
            try:
                message = self._stdout_queue.get(timeout=0.05)
            except Empty as error:
                process = self._process
                if process is None or process.poll() is not None:
                    raise MCPClientPortError(
                        code=MCPClientPortErrorCode.CONNECTION_CLOSED,
                        message="mcp child exited before responding",
                        dispatch_started=True,
                        request_id=request_id,
                    ) from error
                continue
            if str(message.get("id")) != request_id:
                raise MCPClientPortError(
                    code=MCPClientPortErrorCode.MALFORMED_RESPONSE,
                    message="unexpected response id",
                    dispatch_started=True,
                    request_id=request_id,
                )
            if "error" in message:
                error_payload = cast(dict[str, object], message["error"])
                # A structured error response proves the child process ran the
                # request and answered; only the server can know whether that
                # answer came before or after any Google dispatch occurred.
                raw_certainty = error_payload.get("delivery_certainty")
                try:
                    certainty = DeliveryCertainty(str(raw_certainty))
                except ValueError:
                    certainty = (
                        DeliveryCertainty.MAY_HAVE_BEEN_SENT
                        if bool(error_payload.get("dispatch_started", True))
                        else DeliveryCertainty.NOT_SENT
                    )
                try:
                    error_code = MCPClientPortErrorCode(
                        str(error_payload.get("code", "MALFORMED_RESPONSE"))
                    )
                except ValueError:
                    error_code = MCPClientPortErrorCode.MALFORMED_RESPONSE
                raise MCPClientPortError(
                    code=error_code,
                    message=str(error_payload.get("message", "mcp request failed")),
                    delivery_certainty=certainty,
                    request_id=request_id,
                )
            response_payload = cast(JsonObject, message.get("payload", {}))
            return response_payload
        raise MCPClientPortError(
            code=MCPClientPortErrorCode.TIMEOUT,
            message="mcp request timed out",
            dispatch_started=True,
            request_id=request_id,
        )

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            if len(line.encode("utf-8")) > MANIFEST_MESSAGE_LIMIT_BYTES:
                self._last_safe_error_code = MCPClientPortErrorCode.MALFORMED_RESPONSE.value
                continue
            try:
                message = cast(JsonObject, json.loads(line))
            except json.JSONDecodeError:
                self._last_safe_error_code = MCPClientPortErrorCode.MALFORMED_RESPONSE.value
                continue
            self._stdout_queue.put(message)

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            self._stderr_lines.append(line.rstrip())


@dataclass(frozen=True, slots=True)
class _BoundStdioRuntime:
    client: StdioMCPClientAdapter

    def runtime_metadata(self) -> MCPRuntimeMetadata:
        return self.client.runtime_metadata()

    def list_tools(self) -> list[MCPToolDescriptorV1]:
        return self.client._list_tools()

    def call_tool(
        self,
        tool_id: str,
        arguments: JsonValue,
        timeout_ms: int,
    ) -> MCPToolCallResultV1:
        return self.client._call_tool(tool_id, arguments, timeout_ms)

    def restart_once(self) -> MCPRestartResultV1:
        return self.client._restart_once()

    def close(self) -> None:
        self.client.close()
