"""Host and origin validation helpers."""

from __future__ import annotations


def normalize_host_header(host_header: str | None) -> str | None:
    if host_header is None:
        return None
    normalized = host_header.strip().lower()
    return normalized or None


def build_expected_origin(*, host: str, port: int) -> str:
    return f"http://{host}:{port}"
