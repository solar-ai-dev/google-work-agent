from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from google_work_agent.domain.action.model import EffectType


@dataclass(frozen=True, slots=True)
class SemanticRouteCandidate:
    input_resource_types: tuple[str, ...]
    output_pairs: tuple[tuple[str, EffectType], ...]
    output_mode: Literal["ANSWER", "ACTION"]
    analysis_requirement: Literal["NONE", "REQUIRED"]
