"""DEV-only settings owned by the local MCP credential provider."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEVELOPMENT_ENVIRONMENT = "DEVELOPMENT"


@dataclass(frozen=True, slots=True)
class GoogleOAuthSettings:
    """Sanitized OAuth configuration; client IDs must not be logged or serialized."""

    google_oauth_client_id: str | None = field(repr=False)
    google_oauth_client_secret: str | None = field(default=None, repr=False)

    @classmethod
    def load(
        cls,
        *,
        runtime_environment: str,
        environment: dict[str, str] | None = None,
    ) -> GoogleOAuthSettings:
        values = (
            _load_env_file(PROJECT_ROOT / ".env.local")
            if runtime_environment.upper() == DEVELOPMENT_ENVIRONMENT
            else {}
        )
        values.update(dict(os.environ) if environment is None else environment)
        client_id = values.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        client_secret = (
            values.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
            if runtime_environment.upper() == DEVELOPMENT_ENVIRONMENT
            else ""
        )
        return cls(
            google_oauth_client_id=client_id or None,
            google_oauth_client_secret=client_secret or None,
        )


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = value.strip().strip("\"'")
    return values
