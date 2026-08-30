"""Thin adapter for deterministic planning.build_dependencies."""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.adapters.langgraph.subgraphs.planning.projections import (
    build_dependencies_projection,
)
from google_work_agent.application.agents.planning.build_dependencies import build_dependencies


def build_dependencies_node(state: Mapping[str, object]) -> dict[str, object]:
    projected = build_dependencies_projection.project_build_dependencies_input(state)
    seeds = projected["action_seeds"]
    return {"dependency_candidates": list(build_dependencies(seeds))}  # type: ignore[arg-type]
