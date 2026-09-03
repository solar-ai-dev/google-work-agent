from google_work_agent.application.use_cases.trace_event.emit_trace_event import (
    EmitTraceEventHandler,
)


def test_emit_trace_event__has_exact__application_owner() -> None:
    assert (
        EmitTraceEventHandler.__module__
        == "google_work_agent.application.use_cases.trace_event.emit_trace_event"
    )
    assert EmitTraceEventHandler.__name__ == "EmitTraceEventHandler"
