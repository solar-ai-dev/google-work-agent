"""Historical integration-fixture helper retained while Review tests use exact owner files."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def _review_output(
    status: str,
    *,
    issues: Sequence[Mapping[str, object]] | None = None,
    confirmation: Mapping[str, object] | None = None,
    blockers: list[str] | None = None,
    additional_acquisition_request: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build the historical queued-provider payload used by pre-cutover suites."""
    return {
        "schema_version": 2,
        "status": status,
        "summary": "Review completed.",
        "issues": [dict(issue) for issue in (issues or ())],
        "confirmation": None if confirmation is None else dict(confirmation),
        "blockers": list(blockers or ()),
        "additional_acquisition_request": additional_acquisition_request,
    }


__all__ = ["_review_output"]
