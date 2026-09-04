import type { RunSnapshot } from "../../api/contract";

const EXECUTING_RUN_STATUSES = new Set([
  "CREATED",
  "ANALYZING",
  "RETRIEVING",
  "PLANNING",
  "EXECUTING",
  "VERIFYING",
  "CANCEL_REQUESTED",
]);

export function isWorkflowExecutionActive(snapshot: RunSnapshot | null): boolean {
  return snapshot !== null && EXECUTING_RUN_STATUSES.has(snapshot.run.status);
}
