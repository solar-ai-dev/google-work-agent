"""Generate the one-time launcher bootstrap secret."""

from __future__ import annotations

import secrets


def create_bootstrap_secret() -> str:
    """Return at least 256 bits of CSPRNG material without persisting it."""

    return secrets.token_urlsafe(32)
