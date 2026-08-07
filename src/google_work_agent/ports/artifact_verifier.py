"""Artifact verification contracts for child-process launch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ArtifactSignatureDecision:
    allowed: bool
    detail: str | None = None


class ArtifactSignatureVerifier(Protocol):
    """Verify a launchable artifact before production execution."""

    def verify(
        self,
        *,
        executable_path: str,
        expected_binary_sha256: str,
    ) -> ArtifactSignatureDecision:
        """Return whether the artifact is safe to launch."""
