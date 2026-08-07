"""Fetch Metadata validation helpers."""

from __future__ import annotations

BLOCKED_FETCH_DESTINATIONS = {"document", "embed", "frame", "iframe", "image", "object", "script"}
ALLOWED_MUTATION_FETCH_MODES = {"cors", "same-origin"}


def validate_fetch_metadata(
    *,
    site: str | None,
    mode: str | None,
    destination: str | None,
    require_headers: bool,
    allow_missing: bool = False,
) -> bool:
    normalized_site = _normalize(site)
    normalized_mode = _normalize(mode)
    normalized_destination = _normalize(destination)
    if normalized_site is None:
        return allow_missing and not require_headers
    if normalized_site != "same-origin":
        return False
    if require_headers and normalized_mode is None:
        return False
    if normalized_mode in {"navigate", "no-cors"}:
        return False
    return normalized_destination not in BLOCKED_FETCH_DESTINATIONS


def validate_mutation_fetch_metadata(
    *,
    site: str | None,
    mode: str | None,
    destination: str | None,
) -> bool:
    normalized_site = _normalize(site)
    normalized_mode = _normalize(mode)
    normalized_destination = _normalize(destination)
    if normalized_site != "same-origin":
        return False
    if normalized_mode not in ALLOWED_MUTATION_FETCH_MODES:
        return False
    return normalized_destination in {None, "", "empty"}


def _normalize(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None
