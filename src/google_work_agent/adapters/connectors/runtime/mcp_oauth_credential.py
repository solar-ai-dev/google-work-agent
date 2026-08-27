"""Connector OAuth boundary implemented through MCP runtime operations."""

from typing import Literal, cast

from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.ports.connector.mcp_client_port import JsonValue, MCPClientPort
from google_work_agent.ports.connector.oauth_credential_port import (
    AuthorizationStartV1,
    ConnectionMetadataV1,
    RevokeResultV1,
)
from google_work_agent.ports.google_oauth import OAuthEnvironment
from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)


class McpOAuthCredentialAdapter:
    def __init__(
        self,
        *,
        runtime_registry: ConnectorRuntimeRegistry,
        mcp_client: MCPClientPort,
        timeout_ms: int = 30_000,
    ) -> None:
        self._runtime_registry = runtime_registry
        self._mcp_client = mcp_client
        self._timeout_ms = timeout_ms

    def start_authorization(
        self,
        connector_id: str,
        environment: OAuthEnvironment,
        requested_scopes: tuple[str, ...],
        operation_ref: str,
    ) -> AuthorizationStartV1:
        _require_connector_id(connector_id)
        if not requested_scopes or any(not scope.strip() for scope in requested_scopes):
            raise ValueError("requested_scopes must contain nonblank values")
        _require_operation_ref(operation_ref)
        payload = self._call(
            connector_id,
            "google.oauth.start",
            {
                "environment": environment.value,
                "requested_scopes": list(requested_scopes),
                "operation_ref": operation_ref,
            },
        )
        return AuthorizationStartV1(
            schema_version=1,
            authorization_url=str(payload["authorization_url"]),
            callback_id=str(payload["flow_id"]),
        )

    def reconcile_authorization_start(
        self, connector_id: str, operation_ref: str
    ) -> OperationalReconcileResultV1:
        _require_connector_id(connector_id)
        _require_operation_ref(operation_ref)
        return self._reconcile(
            connector_id,
            "google.oauth.reconcile_start",
            {"operation_ref": operation_ref},
        )

    def refresh_access(self, connector_id: str, account_id: str) -> str:
        _require_connector_id(connector_id)
        _require_account_id(account_id)
        payload = self._call(
            connector_id,
            "google.connection.refresh",
            {"account_id": account_id},
        )
        return str(payload["access_context_handle"])

    def get_connection_status(self, connector_id: str) -> ConnectionMetadataV1:
        _require_connector_id(connector_id)
        return self._status(
            connector_id,
            self._call(connector_id, "google.connection.get", {}),
        )

    def revoke_connection(
        self,
        connector_id: str,
        account_id: str,
        operation_ref: str,
    ) -> RevokeResultV1:
        _require_connector_id(connector_id)
        _require_account_id(account_id)
        _require_operation_ref(operation_ref)
        payload = self._call(
            connector_id,
            "google.connection.disconnect",
            {"account_id": account_id, "operation_ref": operation_ref},
        )
        return RevokeResultV1(
            schema_version=1,
            revocation_attempted=bool(payload["revoke_attempted"]),
            local_credential_deleted=bool(payload["credential_deleted"]),
            connection_status=("DISCONNECTED" if bool(payload["disconnected"]) else "UNAVAILABLE"),
        )

    def reconcile_revoke_connection(
        self,
        connector_id: str,
        account_id: str,
        operation_ref: str,
    ) -> OperationalReconcileResultV1:
        _require_connector_id(connector_id)
        _require_account_id(account_id)
        _require_operation_ref(operation_ref)
        return self._reconcile(
            connector_id,
            "google.connection.reconcile_disconnect",
            {"account_id": account_id, "operation_ref": operation_ref},
        )

    def _call(
        self, connector_id: str, method: str, arguments: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        self._runtime_registry.resolve(connector_id)
        response = self._mcp_client.call_tool(
            connector_id,
            method,
            arguments,
            self._timeout_ms,
        )
        if response.transport_status != "OK" or not isinstance(response.payload, dict):
            raise RuntimeError(response.error_code or "OAUTH_MCP_CALL_FAILED")
        return cast(dict[str, JsonValue], response.payload)

    @staticmethod
    def _status(connector_id: str, payload: dict[str, JsonValue]) -> ConnectionMetadataV1:
        raw_state = str(payload["credential_state"])
        status: Literal[
            "CONNECTING", "CONNECTED", "DISCONNECTED", "REAUTH_REQUIRED", "UNAVAILABLE"
        ] = (
            "CONNECTED"
            if bool(payload["connected"])
            else "REAUTH_REQUIRED"
            if bool(payload["reauth_required"])
            else "UNAVAILABLE"
            if raw_state in {"KEYRING_UNAVAILABLE", "ERROR"}
            else "DISCONNECTED"
        )
        return ConnectionMetadataV1(
            schema_version=1,
            connector_id=connector_id,
            account_id=None,
            display_email=_optional_string(payload.get("account_email")),
            connection_status=status,
            granted_scopes=tuple(
                str(item) for item in cast(list[object], payload["granted_scopes"])
            ),
            missing_required_scopes=tuple(
                str(item) for item in cast(list[object], payload["missing_scopes"])
            ),
        )

    def _reconcile(
        self, connector_id: str, method: str, arguments: dict[str, JsonValue]
    ) -> OperationalReconcileResultV1:
        payload = self._call(connector_id, method, arguments)
        raw_status = str(payload.get("status", ""))
        if raw_status not in {"COMPLETED", "SAFE_TO_RETRY", "UNCERTAIN"}:
            raise RuntimeError("OAUTH_RECONCILE_RESULT_INVALID")
        return OperationalReconcileResultV1(
            status=cast(Literal["COMPLETED", "SAFE_TO_RETRY", "UNCERTAIN"], raw_status),
            result_ref=_optional_string(payload.get("result_ref")),
            bounded_result=payload.get("bounded_result"),
        )


def _optional_string(value: JsonValue) -> str | None:
    return value if isinstance(value, str) and value else None


def _require_connector_id(value: str) -> None:
    if not value.strip():
        raise ValueError("connector_id is required")


def _require_account_id(value: str) -> None:
    if not value.strip():
        raise ValueError("account_id is required")


def _require_operation_ref(value: str) -> None:
    if not value.strip():
        raise ValueError("operation_ref is required")


__all__ = ["McpOAuthCredentialAdapter"]
