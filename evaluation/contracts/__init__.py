"""Current strict Evaluation contracts."""

from evaluation.contracts.canonical_case import CanonicalCaseV7, EndStateGoldV1
from evaluation.contracts.context_ready_snapshot import (
    ContextReadySnapshotV1,
    EvaluationPolicyProjectionV1,
)
from evaluation.contracts.e2e_projection import E2EProjectionV5
from evaluation.contracts.product_episode_projection import ProductEpisodeE2EProjectionV1
from evaluation.contracts.routing_trajectory_projection import RoutingTrajectoryProjectionV2

__all__ = [
    "CanonicalCaseV7",
    "ContextReadySnapshotV1",
    "E2EProjectionV5",
    "EndStateGoldV1",
    "EvaluationPolicyProjectionV1",
    "ProductEpisodeE2EProjectionV1",
    "RoutingTrajectoryProjectionV2",
]
