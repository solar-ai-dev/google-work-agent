"""Typed projection of the latest durable Retrieval checkpoint."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class RetrievalHeadV1:
    schema_version: Literal[1]
    run_id: str
    langgraph_thread_id: str
    retrieval_revision: int
    retrieval_artifact_id: str
    checkpoint_id: str
    checkpoint_generation: int
