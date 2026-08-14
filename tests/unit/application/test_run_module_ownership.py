from google_work_agent.application import (
    conversation_lifecycle,
    run_contracts,
    run_lifecycle,
    start_run,
    write_action_mutation,
    write_action_mutation_contracts,
)


def test_start_run_remains_a_compatibility_facade() -> None:
    assert start_run.CreateConversationCommand is run_contracts.CreateConversationCommand
    assert start_run.CreateConversationService is conversation_lifecycle.CreateConversationService
    assert start_run.StartRunCommand is run_contracts.StartRunCommand
    assert start_run.StartRunService is run_lifecycle.StartRunService
    assert start_run.ResumeRunService is run_lifecycle.ResumeRunService
    assert start_run.ModifyWriteActionCommand is (
        write_action_mutation_contracts.ModifyWriteActionCommand
    )
    assert start_run.ModifyWriteActionService is write_action_mutation.ModifyWriteActionService
    assert start_run.RejectWriteActionService is write_action_mutation.RejectWriteActionService
