import google_work_agent.application.run_lifecycle as run_lifecycle
import google_work_agent.application.start_run as start_run
from google_work_agent.application.use_cases.conversation.create_conversation import (
    CreateConversationCommand,
)
from google_work_agent.application.use_cases.run.resume_run import ResumeRunCommand


def test_start_run_remains_a_compatibility_facade() -> None:
    assert start_run.CreateConversationCommand is CreateConversationCommand
    assert start_run.ResumeRunCommand is ResumeRunCommand
    assert start_run.ResumeRunService is run_lifecycle.ResumeRunService
    assert not hasattr(start_run, "ModifyWriteActionCommand")
    assert not hasattr(start_run, "ModifyWriteActionService")
    assert not hasattr(start_run, "RejectWriteActionService")
