"""One-time Bootstrap Secret production."""

import secrets


def create_bootstrap_secret() -> str:
    """Create a CSPRNG-backed secret with at least 256 bits of entropy."""

    return secrets.token_urlsafe(32)
