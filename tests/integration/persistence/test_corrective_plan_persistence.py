"""Corrective-plan persistence behavior over the shared integration harness."""

from pathlib import Path

import pytest

from tests.support import corrective_plan_persistence as scenarios


def test_reserved_corrective_plan__preserves_plan_identity__and_remaps_children(
    tmp_path: Path,
) -> None:
    scenarios.assert_reserved_corrective_plan_preserves_plan_identity_and_remaps_children(tmp_path)


def test_save_success__publish_failure_retries__with_publish_only(tmp_path: Path) -> None:
    scenarios.assert_save_success_publish_failure_retries_with_publish_only(tmp_path)


@pytest.mark.parametrize("drift_kind", ["arguments", "dependency", "evidence"])
def test_candidate_drift__after_committed__save_fails_closed(
    tmp_path: Path,
    drift_kind: str,
) -> None:
    scenarios.assert_candidate_drift_after_committed_save_fails_closed(tmp_path, drift_kind)


def test_already_published_replay__has_no_second_save__or_publish_side_effect(
    tmp_path: Path,
) -> None:
    scenarios.assert_already_published_replay_has_no_second_save_or_publish_side_effect(tmp_path)


def test_reserved_corrective_marker__survives_failed_compiled__checkpoint_and_is_consumed(
    tmp_path: Path,
) -> None:
    scenarios.assert_reserved_corrective_marker_survives_failed_compiled_checkpoint_and_is_consumed(
        tmp_path
    )
