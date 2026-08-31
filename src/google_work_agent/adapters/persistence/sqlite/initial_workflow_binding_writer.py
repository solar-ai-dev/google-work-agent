"""SQLite transaction adapter for the initial workflow binding only."""

import sqlite3

from google_work_agent.ports.system.contracts.workflow_binding import WorkflowBindingV1


class SqliteInitialWorkflowBindingWriter:
    """Participate in StartRun's UoW without exposing runtime checkpoint operations."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create_workflow_binding(self, binding: WorkflowBindingV1) -> None:
        existing = self._connection.execute(
            """SELECT workflow_key, run_id, langgraph_thread_id, graph_profile,
                      graph_version, requested_mode, created_at_ms
               FROM workflow_bindings WHERE run_id=?;""",
            (binding.run_id,),
        ).fetchone()
        if existing is not None:
            actual = (
                str(existing["workflow_key"]),
                str(existing["run_id"]),
                str(existing["langgraph_thread_id"]),
                str(existing["graph_profile"]),
                str(existing["graph_version"]),
                str(existing["requested_mode"]),
                int(existing["created_at_ms"]),
            )
            expected = (
                binding.workflow_key,
                binding.run_id,
                binding.langgraph_thread_id,
                binding.graph_profile,
                binding.graph_version,
                binding.requested_mode,
                binding.created_at_ms,
            )
            if actual != expected:
                raise sqlite3.IntegrityError("Run already has a different workflow binding")
            return
        self._connection.execute(
            """INSERT INTO workflow_bindings (
                workflow_key, run_id, langgraph_thread_id, graph_profile,
                graph_version, requested_mode, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?);""",
            (
                binding.workflow_key,
                binding.run_id,
                binding.langgraph_thread_id,
                binding.graph_profile,
                binding.graph_version,
                binding.requested_mode,
                binding.created_at_ms,
            ),
        )
