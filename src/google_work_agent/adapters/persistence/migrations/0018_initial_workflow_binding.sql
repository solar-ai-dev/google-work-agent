PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS workflow_bindings (
    workflow_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    langgraph_thread_id TEXT NOT NULL UNIQUE,
    graph_profile TEXT NOT NULL,
    graph_version TEXT NOT NULL,
    requested_mode TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

COMMIT;

PRAGMA foreign_key_check;
