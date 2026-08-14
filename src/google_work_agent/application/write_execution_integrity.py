"""Integrity helpers for claimed write execution."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from hashlib import sha256
from hmac import compare_digest
from hmac import new as hmac_new
from json import loads
from typing import cast

from google_work_agent.domain import calculate_canonical_json_hash, canonicalize_json_value

CLAIM_TOKEN_VERSION = "v1"


def normalize_claim_token_payload(payload: dict[str, object]) -> bytes:
    return canonicalize_json_value(payload).encode("utf-8")


def calculate_claim_token_signature(payload_bytes: bytes, *, signing_secret: str) -> str:
    return hmac_new(signing_secret.encode("utf-8"), payload_bytes, sha256).hexdigest()


def issue_claim_token(payload: dict[str, object], *, signing_secret: str) -> str:
    payload_bytes = normalize_claim_token_payload(payload)
    encoded_payload = urlsafe_b64encode(payload_bytes).decode("ascii")
    signature = calculate_claim_token_signature(payload_bytes, signing_secret=signing_secret)
    return f"{encoded_payload}.{signature}"


def read_claim_token(token: str, *, signing_secret: str) -> dict[str, object]:
    encoded_payload, signature = token.split(".", 1)
    payload_bytes = urlsafe_b64decode(encoded_payload.encode("ascii"))
    expected_signature = calculate_claim_token_signature(
        payload_bytes, signing_secret=signing_secret
    )
    if not compare_digest(signature, expected_signature):
        raise PermissionError("claim token signature mismatch")
    payload = loads(payload_bytes.decode("utf-8"))
    if str(payload.get("version")) != CLAIM_TOKEN_VERSION:
        raise PermissionError("claim token version mismatch")
    return cast(dict[str, object], payload)


def calculate_recovery_fingerprint(
    *, tool_name: str, arguments_hash: str, source_snapshot_hash: str
) -> str:
    return calculate_canonical_json_hash(
        {
            "tool_name": tool_name,
            "arguments_hash": arguments_hash,
            "source_snapshot_hash": source_snapshot_hash,
        }
    )
