"""Materialize an explicit evaluated LOCAL_CAPABLE product decision."""

from __future__ import annotations

from pathlib import Path

from google_work_agent.ports.llm.local_model_product_decision import (
    LocalModelProductDecisionV1,
)


def generate_local_model_product_decision(
    *, decision: LocalModelProductDecisionV1, output_path: Path
) -> LocalModelProductDecisionV1:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(decision.to_canonical_bytes() + b"\n")
    return decision


__all__ = ["generate_local_model_product_decision"]
