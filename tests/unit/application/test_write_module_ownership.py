from google_work_agent.application import (
    write_actions,
    write_approval,
    write_cancellation,
    write_claim,
    write_execution,
    write_execution_contracts,
    write_plan,
    write_plan_contracts,
    write_recovery,
    write_recovery_contracts,
    write_verification,
)


def test_write_actions_remains_a_compatibility_facade() -> None:
    assert write_actions.SaveWritePlanService is write_plan.SaveWritePlanService
    assert write_actions.SaveWritePlanCommand is write_plan_contracts.SaveWritePlanCommand
    assert write_actions.ApproveWriteActionService is write_approval.ApproveWriteActionService
    assert write_actions.ClaimWriteActionService is write_claim.ClaimWriteActionService
    assert write_actions.ExecuteWriteActionService is write_execution.ExecuteWriteActionService
    assert write_actions.VerifyWriteActionService is write_verification.VerifyWriteActionService
    assert write_actions.RecoverUnknownCreateActionService is (
        write_recovery.RecoverUnknownCreateActionService
    )
    assert write_actions.RecoveryResolutionKind is (write_recovery_contracts.RecoveryResolutionKind)
    assert write_actions.RequestRunCancellationService is (
        write_cancellation.RequestRunCancellationService
    )
    assert write_actions.WriteActionResponse is write_execution_contracts.WriteActionResponse
    assert write_actions.calculate_verification_diff is (
        write_verification.calculate_verification_diff
    )
