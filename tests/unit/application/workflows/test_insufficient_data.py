import pytest

from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.application.agents.retrieval.assess_sufficiency import (
    InsufficientDataContext,
    InsufficientDataDisposition,
    InsufficientDataIssue,
    ResolutionSource,
    decide_insufficient_data,
)


def _context(
    *,
    source: ResolutionSource,
    safety_critical: bool = False,
    budget_remaining: int = 1,
    read_only: bool = False,
    partial: bool = False,
    write_gap: bool = False,
    user_can_resolve: bool = False,
) -> InsufficientDataContext:
    return InsufficientDataContext(
        issues=(
            InsufficientDataIssue(
                issue_type="required-data-gap",
                required=True,
                resolution_source=source,
                safety_critical=safety_critical,
            ),
        ),
        budget_remaining=budget_remaining,
        read_only=read_only,
        evidence_supported_partial_possible=partial,
        write_required_data_missing=write_gap,
        user_can_resolve_write_gap=user_can_resolve,
    )


@pytest.mark.parametrize(
    ("context", "expected"),
    [
        (_context(source=ResolutionSource.POLICY), InsufficientDataDisposition.BLOCKED),
        (
            _context(source=ResolutionSource.GOOGLE, safety_critical=True),
            InsufficientDataDisposition.BLOCKED,
        ),
        (
            _context(source=ResolutionSource.USER),
            InsufficientDataDisposition.NEEDS_CONFIRMATION,
        ),
        (
            _context(source=ResolutionSource.ROUTE),
            InsufficientDataDisposition.ROUTE_RECONSIDERATION_REQUIRED,
        ),
        (
            _context(source=ResolutionSource.GOOGLE),
            InsufficientDataDisposition.RETRIEVE_MORE,
        ),
        (
            _context(
                source=ResolutionSource.GOOGLE,
                budget_remaining=0,
                read_only=True,
                partial=True,
            ),
            InsufficientDataDisposition.PARTIAL,
        ),
        (
            _context(
                source=ResolutionSource.GOOGLE,
                budget_remaining=0,
                write_gap=True,
            ),
            InsufficientDataDisposition.BLOCKED,
        ),
    ],
)
def test_canonical_insufficient_data_precedence(
    context: InsufficientDataContext,
    expected: InsufficientDataDisposition,
) -> None:
    assert decide_insufficient_data(context) is expected


def test_write_gap_can_only_request_user_confirmation_when_user_can_resolve() -> None:
    context = InsufficientDataContext(
        issues=(),
        budget_remaining=0,
        read_only=False,
        evidence_supported_partial_possible=True,
        write_required_data_missing=True,
        user_can_resolve_write_gap=True,
    )

    assert decide_insufficient_data(context) is InsufficientDataDisposition.NEEDS_CONFIRMATION


def test_single_three_and_six_profiles_share_the_same_guard_semantics() -> None:
    context = _context(source=ResolutionSource.POLICY)

    decisions = {
        profile: decide_insufficient_data(context)
        for profile in (
            GraphProfile.SINGLE_BASELINE,
            GraphProfile.THREE_STAGE,
            GraphProfile.SIX_ROLE_BASELINE,
        )
    }

    assert set(decisions.values()) == {InsufficientDataDisposition.BLOCKED}
