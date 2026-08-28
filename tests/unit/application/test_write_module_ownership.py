from pathlib import Path

import tests.support.legacy_write.write_actions as write_actions
import tests.support.legacy_write.write_cancellation as write_cancellation
import tests.support.legacy_write.write_claim as write_claim
import tests.support.legacy_write.write_execution as write_execution
import google_work_agent.application.write_execution_contracts as write_execution_contracts
import google_work_agent.application.write_plan as write_plan
import google_work_agent.application.write_plan_contracts as write_plan_contracts
import tests.support.legacy_write.write_recovery as write_recovery
import google_work_agent.application.write_recovery_contracts as write_recovery_contracts
import tests.support.legacy_write.write_verification as write_verification


def test_legacy_write_facade_is_test_only_and_absent_from_production() -> None:
    application_root = Path(__file__).parents[3] / "src/google_work_agent/application"
    for name in (
        "write_actions.py",
        "write_cancellation.py",
        "write_claim.py",
        "write_execution.py",
        "write_recovery.py",
        "write_result_persistence.py",
        "write_verification.py",
    ):
        assert not (application_root / name).exists()
    assert write_actions.SaveWritePlanService is write_plan.SaveWritePlanService
    assert write_actions.SaveWritePlanCommand is write_plan_contracts.SaveWritePlanCommand
    assert not hasattr(write_actions, "ApproveWriteActionService")
    assert write_actions.ClaimWriteActionService is write_claim.ClaimWriteActionService
    assert write_actions.ExecuteWriteActionService is write_execution.ExecuteWriteActionService
    assert write_actions.VerifyWriteActionService is write_verification.VerifyWriteActionService
    assert write_actions.RecoverUnknownCreateActionService is (
        write_recovery.RecoverUnknownCreateActionService
    )
    assert not hasattr(write_actions, "RecoveryResolutionKind")
    assert not hasattr(write_recovery_contracts, "RecoveryResolutionKind")
    assert write_actions.RequestRunCancellationService is (
        write_cancellation.RequestRunCancellationService
    )
    assert write_actions.WriteActionResponse is write_execution_contracts.WriteActionResponse
    assert write_actions.calculate_verification_diff is (
        write_verification.calculate_verification_diff
    )
