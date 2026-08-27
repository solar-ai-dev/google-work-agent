"""Canonical TTL contract for short-lived MCP write claims.

Approval lifetime is intentionally owned elsewhere.  A Claim is an execution
capability issued immediately before MCP dispatch, so its lifetime must never
be derived from an Approval's lifetime.
"""

CLAIM_CONTEXT_DEFAULT_TTL_MS = 30_000
CLAIM_CONTEXT_MAX_TTL_MS = 60_000


def validate_claim_ttl_ms(ttl_ms: int) -> int:
    """Return a valid claim TTL, failing closed outside the canonical bound."""
    if not isinstance(ttl_ms, int) or isinstance(ttl_ms, bool):
        raise ValueError("claim TTL must be an integer")
    if ttl_ms <= 0 or ttl_ms > CLAIM_CONTEXT_MAX_TTL_MS:
        raise ValueError("claim TTL must be > 0 and <= CLAIM_CONTEXT_MAX_TTL_MS")
    return ttl_ms
