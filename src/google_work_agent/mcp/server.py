"""Canonical MCP server module.

Provider mechanics remain in the compatibility implementation, but Claim TTL
validation is bound to the Domain claim contract before that implementation is
exposed. This keeps one runtime TTL authority for both Application issuance and
MCP validation.
"""

from __future__ import annotations

import sys

from google_work_agent.domain.claim_contract import CLAIM_CONTEXT_MAX_TTL_MS
from google_work_agent.mcp import _legacy_server_impl as _impl

# One-way compatibility projection: legacy handlers read this module-global at
# validation time, so bind it to the Domain authority before exposing them.
_impl.CLAIM_CONTEXT_MAX_TTL_MS = CLAIM_CONTEXT_MAX_TTL_MS

if __name__ == "__main__":
    _impl.main()
else:
    # Return the implementation module itself so monkeypatching/private helper
    # lookups retain normal module-global semantics in tests and verified_server.
    sys.modules[__name__] = _impl
