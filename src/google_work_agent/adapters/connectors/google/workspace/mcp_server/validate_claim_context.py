"""Google Workspace write claim validation authority."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import cast

from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.ports.connector.claim_context_contract import (
    CLAIM_CONTEXT_MAX_TTL_MS,
)


def validate_claim_context(
    state: object,
    *,
    tool_name: str,
    claim_context: object,
    execution_arguments: dict[str, object],
) -> None:
    # Local import avoids making the exact authority a second server entrypoint.
    from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
        credential_provider,
    )

    runtime_state = cast(credential_provider.GoogleWorkspaceCredentialProvider, state)
    if (
        runtime_state.session_key is None
        or runtime_state.service_instance_id is None
        or runtime_state.process_instance_id is None
    ):
        raise credential_provider._WorkspaceToolError("CLAIM_SERVICE_UNAVAILABLE")
    if not isinstance(claim_context, dict):
        raise credential_provider._WorkspaceToolError("CLAIM_MISSING")
    claim = cast(dict[str, object], claim_context)
    if any(field not in claim for field in credential_provider.CLAIM_CONTEXT_REQUIRED_FIELDS):
        raise credential_provider._WorkspaceToolError("CLAIM_MISSING")
    if claim.get("claim_version") != credential_provider.CLAIM_CONTEXT_VERSION:
        raise credential_provider._WorkspaceToolError("CLAIM_VERSION_MISMATCH")
    signature = claim.get("signature")
    if not isinstance(signature, str) or not signature:
        raise credential_provider._WorkspaceToolError("CLAIM_INVALID_SIGNATURE")
    unsigned = {key: value for key, value in claim.items() if key != "signature"}
    normalized = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    expected_signature = hmac.new(
        bytes.fromhex(runtime_state.session_key), normalized, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise credential_provider._WorkspaceToolError("CLAIM_INVALID_SIGNATURE")
    for identity_field in ("action_id", "approval_id", "execution_attempt_id"):
        value = claim.get(identity_field)
        if not isinstance(value, str) or not value:
            raise credential_provider._WorkspaceToolError("CLAIM_MALFORMED")
    if str(claim.get("tool_name")) != tool_name:
        raise credential_provider._WorkspaceToolError("CLAIM_TOOL_MISMATCH")
    if str(claim.get("service_instance_id")) != runtime_state.service_instance_id:
        raise credential_provider._WorkspaceToolError("CLAIM_SERVICE_INSTANCE_MISMATCH")
    if str(claim.get("mcp_process_instance_id")) != runtime_state.process_instance_id:
        raise credential_provider._WorkspaceToolError("CLAIM_PROCESS_INSTANCE_MISMATCH")
    issued_at_ms = claim.get("issued_at_ms")
    expires_at_ms = claim.get("expires_at_ms")
    if not isinstance(issued_at_ms, int) or not isinstance(expires_at_ms, int):
        raise credential_provider._WorkspaceToolError("CLAIM_MALFORMED")
    if expires_at_ms <= issued_at_ms or expires_at_ms - issued_at_ms > CLAIM_CONTEXT_MAX_TTL_MS:
        raise credential_provider._WorkspaceToolError("CLAIM_TTL_EXCEEDED")
    if credential_provider._now_ms() >= expires_at_ms:
        raise credential_provider._WorkspaceToolError("CLAIM_EXPIRED")
    nonce = claim.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        raise credential_provider._WorkspaceToolError("CLAIM_MALFORMED")
    if nonce in runtime_state.used_nonces:
        raise credential_provider._WorkspaceToolError("CLAIM_TOKEN_REUSED")
    for hash_field in ("approval_arguments_hash", "execution_arguments_hash"):
        value = claim.get(hash_field)
        if not isinstance(value, str) or not value:
            raise credential_provider._WorkspaceToolError("CLAIM_MALFORMED")
    recomputed_hash = calculate_canonical_json_hash(execution_arguments)
    if not hmac.compare_digest(recomputed_hash, str(claim["execution_arguments_hash"])):
        raise credential_provider._WorkspaceToolError("CLAIM_ARGUMENTS_MISMATCH")
    runtime_state.used_nonces.add(nonce)


__all__ = ["validate_claim_context"]
