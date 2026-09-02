"""Local service dependency readiness checks."""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from google_work_agent.adapters.connectors.google.workspace.composition import (
    GOOGLE_WORKSPACE_CONNECTOR_ID,
)
from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.adapters.keyring.os_keyring_secret_store import OsKeyringSecretStoreAdapter
from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.ports.keyring.secret_store_port import SecretStorePort
from google_work_agent.ports.system.readiness_port import (
    ReadinessAggregator,
    ReadinessCheckResult,
    ReadinessReport,
    ReadinessState,
)


@dataclass(frozen=True, slots=True)
class LocalServiceReadinessAggregator(ReadinessAggregator):
    database_path: Path
    connector_registry: ConnectorRuntimeRegistry
    project_root: Path
    api_contract_version: str
    mcp_manifest_version: str
    mcp_manifest_path: Path | None = None
    mcp_executable_path: Path | None = None
    prompt_active: bool = True
    allow_unvalidated_prompt: bool = False
    keyring_store: SecretStorePort | None = None

    @property
    def transport(self) -> Any:
        """Expose the connector transport for lifecycle integration and tests."""

        return cast(Any, self.connector_registry.resolve(GOOGLE_WORKSPACE_CONNECTOR_ID))

    def evaluate(self) -> ReadinessReport:
        checks = (
            self._manifest_asset_check(),
            self._api_contract_check(),
            self._sqlite_check(),
            self._domain_check(),
            self._keyring_check(),
            self._mcp_executable_check(),
            self._mcp_check(),
            self._tool_schema_check(),
            self._prompt_activation_check(),
        )
        state = (
            ReadinessState.READY
            if all(check.state is ReadinessState.READY for check in checks)
            else ReadinessState.NOT_READY
        )
        return ReadinessReport(state=state, checks=checks)

    def _sqlite_check(self) -> ReadinessCheckResult:
        try:
            with connect_sqlite(self.database_path) as connection:
                row = connection.execute("SELECT COUNT(*) FROM schema_migrations;").fetchone()
            if row is None or int(row[0]) < 1:
                return ReadinessCheckResult(
                    name="sqlite_migrations",
                    state=ReadinessState.NOT_READY,
                    detail="migration receipts are unavailable",
                )
        except sqlite3.Error:
            return ReadinessCheckResult(
                name="sqlite_migrations",
                state=ReadinessState.NOT_READY,
                detail="sqlite is unavailable",
            )
        return ReadinessCheckResult(name="sqlite_migrations", state=ReadinessState.READY)

    def _manifest_asset_check(self) -> ReadinessCheckResult:
        manifest_ok = self.mcp_manifest_path is not None and self.mcp_manifest_path.is_file()
        asset_ok = (self.project_root / "frontend" / "index.html").is_file()
        if manifest_ok and asset_ok:
            return ReadinessCheckResult(name="manifest_assets", state=ReadinessState.READY)
        return ReadinessCheckResult(
            name="manifest_assets",
            state=ReadinessState.NOT_READY,
            detail="MANIFEST_OR_ASSET_UNAVAILABLE",
        )

    def _api_contract_check(self) -> ReadinessCheckResult:
        if self.api_contract_version:
            return ReadinessCheckResult(name="api_contract", state=ReadinessState.READY)
        return ReadinessCheckResult(
            name="api_contract",
            state=ReadinessState.NOT_READY,
            detail="API_CONTRACT_UNAVAILABLE",
        )

    def _domain_check(self) -> ReadinessCheckResult:
        try:
            with connect_sqlite(self.database_path) as connection:
                row = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'runs';"
                ).fetchone()
        except sqlite3.Error:
            row = None
        if row is not None:
            return ReadinessCheckResult(name="domain_schema", state=ReadinessState.READY)
        return ReadinessCheckResult(
            name="domain_schema",
            state=ReadinessState.NOT_READY,
            detail="DOMAIN_SCHEMA_UNAVAILABLE",
        )

    def _keyring_check(self) -> ReadinessCheckResult:
        if self.keyring_store is not None:
            return ReadinessCheckResult(name="keyring_adapter", state=ReadinessState.READY)
        try:
            OsKeyringSecretStoreAdapter()
        except RuntimeError:
            return ReadinessCheckResult(
                name="keyring_adapter",
                state=ReadinessState.NOT_READY,
                detail="KEYRING_UNAVAILABLE",
            )
        return ReadinessCheckResult(name="keyring_adapter", state=ReadinessState.READY)

    def _mcp_executable_check(self) -> ReadinessCheckResult:
        executable = self.mcp_executable_path or Path(sys.executable)
        if executable.is_absolute() and executable.is_file():
            return ReadinessCheckResult(name="mcp_executable", state=ReadinessState.READY)
        return ReadinessCheckResult(
            name="mcp_executable",
            state=ReadinessState.NOT_READY,
            detail="MCP_EXECUTABLE_UNAVAILABLE",
        )

    def _mcp_check(self) -> ReadinessCheckResult:
        try:
            metadata = cast(
                Any, self.connector_registry.resolve(GOOGLE_WORKSPACE_CONNECTOR_ID)
            ).runtime_metadata()
        except LookupError:
            return ReadinessCheckResult(
                name="mcp_handshake",
                state=ReadinessState.NOT_READY,
                detail="MCP_RUNTIME_UNAVAILABLE",
            )
        if metadata.process_status != "READY" or metadata.process_instance_id is None:
            return ReadinessCheckResult(
                name="mcp_handshake",
                state=ReadinessState.NOT_READY,
                detail=metadata.last_safe_error_code or metadata.process_status,
            )
        return ReadinessCheckResult(name="mcp_handshake", state=ReadinessState.READY)

    def _tool_schema_check(self) -> ReadinessCheckResult:
        try:
            metadata = cast(
                Any, self.connector_registry.resolve(GOOGLE_WORKSPACE_CONNECTOR_ID)
            ).runtime_metadata()
        except LookupError:
            return ReadinessCheckResult(
                name="tool_schema",
                state=ReadinessState.NOT_READY,
                detail="TOOL_SCHEMA_UNAVAILABLE",
            )
        if (
            metadata.protocol_version == self.mcp_manifest_version
            and metadata.available_tool_count > 0
        ):
            return ReadinessCheckResult(name="tool_schema", state=ReadinessState.READY)
        return ReadinessCheckResult(
            name="tool_schema",
            state=ReadinessState.NOT_READY,
            detail="TOOL_SCHEMA_UNAVAILABLE",
        )

    def _prompt_activation_check(self) -> ReadinessCheckResult:
        if self.prompt_active:
            return ReadinessCheckResult(
                name="prompt_activation",
                state=ReadinessState.READY,
                detail="RUNTIME_ACTIVE",
            )
        if self.allow_unvalidated_prompt:
            return ReadinessCheckResult(
                name="prompt_activation",
                state=ReadinessState.READY,
                detail="UNVALIDATED_BASELINE",
            )
        return ReadinessCheckResult(
            name="prompt_activation",
            state=ReadinessState.NOT_READY,
            detail="PROMPT_RUNTIME_INACTIVE",
        )
