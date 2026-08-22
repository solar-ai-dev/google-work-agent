"""Regression coverage for canonical_optional_inputs import wiring.

``ConfirmationResponseV1`` is defined in ``application.workflows.contracts``,
not ``application.workflows.handoff_contracts``. Importing it from the wrong
module breaks ``adapters.langgraph`` package import entirely (this module is
pulled in transitively by ``canonical_optional_subgraphs`` /
``canonical_response_runtime``).
"""

import google_work_agent.application.orchestration.optional_agent_inputs as canonical_optional_inputs
from google_work_agent.application.orchestration.contracts import ConfirmationResponseV1


def test_confirmation_response_v1_is_imported_from_contracts() -> None:
    assert canonical_optional_inputs.ConfirmationResponseV1 is ConfirmationResponseV1
