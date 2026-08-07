"""Loopback bind policy helpers."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address


def normalize_bind_host(host: str) -> str:
    """Normalize the configured bind host for strict loopback validation."""

    normalized = host.strip()
    if not normalized:
        raise ValueError("bind host must not be blank")
    return normalized


@dataclass(frozen=True, slots=True)
class LocalBindPolicy:
    """Validate that the local API binds only to a concrete loopback address."""

    host: str
    port: int

    def validate(self) -> None:
        normalized_host = normalize_bind_host(self.host)
        if not 1 <= self.port <= 65535:
            raise ValueError("bind port must be between 1 and 65535")
        if normalized_host.lower() == "localhost":
            raise ValueError("localhost is not allowed; use 127.0.0.1 explicitly")
        parsed = ip_address(normalized_host)
        if not parsed.is_loopback:
            raise ValueError("bind host must be a loopback address")
        if parsed.version != 4 or normalized_host != "127.0.0.1":
            raise ValueError("bind host must be exactly 127.0.0.1")
