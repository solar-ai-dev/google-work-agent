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
from typing import Any, cast

from google_work_agent.domain import build_p0_tool_registry
from google_work_agent.ports import (
    ArtifactSignatureDecision,
    ArtifactSignatureVerifier,
    MCPControlResponse,
    MCPRuntimeMetadata,
    MCPToolResponse,
    MCPTransportError,
    MCPTransportErrorCode,
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
class MCPManifestTool:
    tool_name: str
    effect_type: str
    required_scope: str
    approval_requirement: str
    verification_policy: str
    recovery_policy: str
    retryable: bool
    input_schema_version: str
    output_schema_version: str
    tool_schema_hash: str
    registry_version: str


@dataclass(frozen=True, slots=True)
class MCPServerManifest:
    manifest_version: str
    protocol_version: str
    tool_registry_version: str
    tools: tuple[MCPManifestTool, ...]

    @classmethod
    def load(cls, path: Path) -> MCPServerManifest:
        raw = path.read_bytes()
        payload = json.loads(normalize_manifest_bytes(raw).decode("utf-8"))
        tools = tuple(
            _manifest_tool_from_payload(cast(dict[str, object], item))
            for item in cast(list[object], payload["tools"])
        )
        return cls(
            manifest_version=str(payload["manifest_version"]),
            protocol_version=str(payload["protocol_version"]),
            tool_registry_version=str(payload["tool_registry_version"]),
            tools=tools,
        )


def build_manifest_payload() -> dict[str, object]:
    registry = build_p0_tool_registry()
    entries = registry.list_entries()
    registry_version = entries[0].registry_version if entries else "2026-08-07.p0"
    tools = [
        {
            "tool_name": entry.tool_name,
            "effect_type": entry.effect_type.value,
            "required_scope": entry.scope,
            "approval_requirement": entry.approval_requirement.value,
            "verification_policy": entry.verification_policy.value,
            "recovery_policy": entry.recovery_policy.value,
            "retryable": entry.retryable,
            "input_schema_version": entry.input_schema_version,
            "output_schema_version": entry.output_schema_version,
            "tool_schema_hash": entry.tool_schema_hash,
            "registry_version": entry.registry_version,
        }
        for entry in entries
    ]
    return {
        "manifest_version": "2026-08-07.p0",
        "protocol_version": PROTOCOL_VERSION,
        "tool_registry_version": registry_version,
        "tools": tools,
    }


def _manifest_tool_from_payload(payload: dict[str, object]) -> MCPManifestTool:
    return MCPManifestTool(
        tool_name=str(payload["tool_name"]),
        effect_type=str(payload["effect_type"]),
        required_scope=str(payload["required_scope"]),
        approval_requirement=str(payload["approval_requirement"]),
        verification_policy=str(payload["verification_policy"]),
        recovery_policy=str(payload["recovery_policy"]),
        retryable=bool(payload["retryable"]),
        input_schema_version=str(payload["input_schema_version"]),
        output_schema_version=str(payload["output_schema_version"]),
        tool_schema_hash=str(payload["tool_schema_hash"]),
        registry_version=str(payload["registry_version"]),
    )


@dataclass(frozen=True, slots=True)
class MCPArtifactConfig:
    executable_path: str
    manifest_path: str
    expected_binary_sha256: str
    expected_manifest_sha256: str
    expected_manifest_version: str
    expected_protocol_version: str
    expected_tool_registry_version: str
    startup_timeout_ms: int
    request_timeout_ms: int
    max_restart_count: int
    environment: str
    service_instance_id: str
    module_name: str = "google_work_agent.mcp.server"
    working_directory: str | None = None
    environment_allowlist: tuple[str, ...] = ("SYSTEMROOT", "WINDIR", "PATH", "TMP", "TEMP")
    extra_environment: dict[str, str] | None = None


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


class SubprocessMCPTransport:
    """Strict stdio client for the local MCP child process."""

    def __init__(
        self,
        *,
        config: MCPArtifactConfig,
        signature_verifier: ArtifactSignatureVerifier | None = None,
    ) -> None:
        self._config = config
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

    def call_tool(self, *, tool_name: str, arguments: dict[str, Any]) -> MCPToolResponse:
        payload = self._request(
            message_type="tool_call",
            body={"tool_name": tool_name, "arguments": arguments},
        )
        return MCPToolResponse(payload=payload)

    def call_control(self, *, method: str, arguments: dict[str, Any]) -> MCPControlResponse:
        payload = self._request(
            message_type="control_call",
            body={"method": method, "arguments": arguments},
        )
        return MCPControlResponse(payload=payload)

    def runtime_metadata(self) -> MCPRuntimeMetadata:
        return MCPRuntimeMetadata(
            process_status=self._status.value,
            protocol_version=self._manifest.protocol_version,
            manifest_version=self._manifest.manifest_version,
            tool_registry_version=self._manifest.tool_registry_version,
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

    def _validate_artifacts(self) -> MCPServerManifest:
        executable_path = Path(self._config.executable_path)
        manifest_path = Path(self._config.manifest_path)
        if not executable_path.is_absolute() or not manifest_path.is_absolute():
            raise MCPTransportError(
                code=MCPTransportErrorCode.ARTIFACT_REJECTED,
                message="artifact paths must be absolute",
            )
        if calculate_file_sha256(executable_path) != self._config.expected_binary_sha256:
            raise MCPTransportError(
                code=MCPTransportErrorCode.ARTIFACT_REJECTED,
                message="binary hash mismatch",
            )
        if calculate_file_sha256(manifest_path) != self._config.expected_manifest_sha256:
            raise MCPTransportError(
                code=MCPTransportErrorCode.ARTIFACT_REJECTED,
                message="manifest hash mismatch",
            )
        if self._config.environment.upper() == "PRODUCTION":
            if self._signature_verifier is None:
                raise MCPTransportError(
                    code=MCPTransportErrorCode.ARTIFACT_REJECTED,
                    message="production launch requires a signature verifier",
                )
            decision = self._signature_verifier.verify(
                executable_path=str(executable_path),
                expected_binary_sha256=self._config.expected_binary_sha256,
            )
            if not decision.allowed:
                raise MCPTransportError(
                    code=MCPTransportErrorCode.ARTIFACT_REJECTED,
                    message=decision.detail or "artifact signature rejected",
                )
        manifest = MCPServerManifest.load(manifest_path)
        if manifest.manifest_version != self._config.expected_manifest_version:
            raise MCPTransportError(
                code=MCPTransportErrorCode.SCHEMA_MISMATCH,
                message="manifest version mismatch",
            )
        if manifest.protocol_version != self._config.expected_protocol_version:
            raise MCPTransportError(
                code=MCPTransportErrorCode.SCHEMA_MISMATCH,
                message="protocol version mismatch",
            )
        if manifest.tool_registry_version != self._config.expected_tool_registry_version:
            raise MCPTransportError(
                code=MCPTransportErrorCode.SCHEMA_MISMATCH,
                message="tool registry version mismatch",
            )
        self._validate_manifest_tools(manifest)
        return manifest

    def _validate_manifest_tools(self, manifest: MCPServerManifest) -> None:
        registry = build_p0_tool_registry()
        expected_names = {entry.tool_name for entry in registry.list_entries()}
        manifest_names = {tool.tool_name for tool in manifest.tools}
        if manifest_names != expected_names:
            raise MCPTransportError(
                code=MCPTransportErrorCode.TOOL_REJECTED,
                message="manifest tool allowlist mismatch",
            )
        for tool in manifest.tools:
            entry = registry.require(tool.tool_name)
            if tool.effect_type != entry.effect_type.value:
                raise MCPTransportError(
                    code=MCPTransportErrorCode.TOOL_REJECTED,
                    message=f"tool effect mismatch: {tool.tool_name}",
                )
            if tool.required_scope != entry.scope:
                raise MCPTransportError(
                    code=MCPTransportErrorCode.TOOL_REJECTED,
                    message=f"tool scope mismatch: {tool.tool_name}",
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
        handshake = self._request(
            message_type="handshake",
            body={
                "service_instance_id": self._config.service_instance_id,
                "session_key": self._session_key,
                "protocol_version": PROTOCOL_VERSION,
            },
        )
        self._process_instance_id = str(handshake["process_instance_id"])
        initialize = self._request(
            message_type="initialize",
            body={
                "manifest_version": self._manifest.manifest_version,
                "tool_registry_version": self._manifest.tool_registry_version,
            },
        )
        self._status = MCPProcessStatus.VALIDATING_TOOLS
        remote_manifest_version = str(initialize["manifest_version"])
        remote_protocol = str(initialize["protocol_version"])
        if remote_manifest_version != self._manifest.manifest_version:
            raise MCPTransportError(
                code=MCPTransportErrorCode.HANDSHAKE_FAILED,
                message="remote manifest mismatch",
            )
        if remote_protocol != self._manifest.protocol_version:
            raise MCPTransportError(
                code=MCPTransportErrorCode.HANDSHAKE_FAILED,
                message="remote protocol mismatch",
            )
        remote_tools = self._request(message_type="list_tools", body={})
        tool_names = tuple(str(name) for name in cast(list[object], remote_tools["tool_names"]))
        if tool_names != tuple(sorted(tool.tool_name for tool in self._manifest.tools)):
            raise MCPTransportError(
                code=MCPTransportErrorCode.TOOL_REJECTED,
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
        if self._config.extra_environment is not None:
            child_env.update(self._config.extra_environment)
        return child_env

    def _request(self, *, message_type: str, body: JsonObject) -> JsonObject:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                self._last_safe_error_code = MCPTransportErrorCode.PROCESS_UNAVAILABLE.value
                if self._restart_count < self._config.max_restart_count:
                    self._restart_count += 1
                    self._start_process()
                    process = self._process
                else:
                    self._status = MCPProcessStatus.FAILED
                    raise MCPTransportError(
                        code=MCPTransportErrorCode.PROCESS_UNAVAILABLE,
                        message="mcp child process unavailable",
                    )
            self._request_counter += 1
            request_id = f"req-{self._request_counter}"
            self._send_json({"id": request_id, "type": message_type, **body})
            try:
                payload = self._wait_for_response(request_id=request_id)
            except MCPTransportError as error:
                error.dispatch_started = True
                self._last_safe_error_code = error.code.value
                if (
                    error.code
                    in {
                        MCPTransportErrorCode.CONNECTION_CLOSED,
                        MCPTransportErrorCode.PROCESS_UNAVAILABLE,
                    }
                    and self._restart_count < self._config.max_restart_count
                ):
                    self._restart_count += 1
                    self._start_process()
                raise
            return payload

    def _send_json(self, payload: JsonObject) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise MCPTransportError(
                code=MCPTransportErrorCode.PROCESS_UNAVAILABLE,
                message="mcp child stdin unavailable",
            )
        line = json.dumps(payload, sort_keys=True)
        try:
            process.stdin.write(line + "\n")
            process.stdin.flush()
        except OSError as error:
            raise MCPTransportError(
                code=MCPTransportErrorCode.CONNECTION_CLOSED,
                message="mcp child stdin closed during dispatch",
                dispatch_started=True,
            ) from error

    def _wait_for_response(self, *, request_id: str) -> JsonObject:
        deadline = time.monotonic() + (self._config.request_timeout_ms / 1000)
        while time.monotonic() < deadline:
            try:
                message = self._stdout_queue.get(timeout=0.05)
            except Empty as error:
                process = self._process
                if process is None or process.poll() is not None:
                    raise MCPTransportError(
                        code=MCPTransportErrorCode.CONNECTION_CLOSED,
                        message="mcp child exited before responding",
                    ) from error
                continue
            if str(message.get("id")) != request_id:
                raise MCPTransportError(
                    code=MCPTransportErrorCode.MALFORMED_RESPONSE,
                    message="unexpected response id",
                )
            if "error" in message:
                error_payload = cast(dict[str, object], message["error"])
                raise MCPTransportError(
                    code=MCPTransportErrorCode(
                        str(error_payload.get("code", "MALFORMED_RESPONSE"))
                    ),
                    message=str(error_payload.get("message", "mcp request failed")),
                )
            response_payload = cast(JsonObject, message.get("payload", {}))
            return response_payload
        raise MCPTransportError(
            code=MCPTransportErrorCode.TIMEOUT,
            message="mcp request timed out",
        )

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            if len(line.encode("utf-8")) > MANIFEST_MESSAGE_LIMIT_BYTES:
                self._last_safe_error_code = MCPTransportErrorCode.MALFORMED_RESPONSE.value
                continue
            try:
                message = cast(JsonObject, json.loads(line))
            except json.JSONDecodeError:
                self._last_safe_error_code = MCPTransportErrorCode.MALFORMED_RESPONSE.value
                continue
            self._stdout_queue.put(message)

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            self._stderr_lines.append(line.rstrip())
