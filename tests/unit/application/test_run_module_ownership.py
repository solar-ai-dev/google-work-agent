import google_work_agent.application.run_lifecycle as run_lifecycle
import google_work_agent.application.start_run as start_run
import google_work_agent.application.write_action_mutation as write_action_mutation
import google_work_agent.application.write_action_mutation_contracts as write_action_mutation_contracts
from google_work_agent.application.use_cases.conversation.create_conversation import (
    CreateConversationCommand,
)
from google_work_agent.application.use_cases.run.resume_run import ResumeRunCommand


def test_start_run_remains_a_compatibility_facade() -> None:
    assert start_run.CreateConversationCommand is CreateConversationCommand
    assert start_run.ResumeRunCommand is ResumeRunCommand
    assert start_run.ResumeRunService is run_lifecycle.ResumeRunService
    assert start_run.ModifyWriteActionCommand is (
        write_action_mutation_contracts.ModifyWriteActionCommand
    )
    assert start_run.ModifyWriteActionService is write_action_mutation.ModifyWriteActionService
    assert start_run.RejectWriteActionService is write_action_mutation.RejectWriteActionService
