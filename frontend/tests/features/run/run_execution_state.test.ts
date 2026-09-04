import { expect, test } from "vitest";
import type { RunSnapshot } from "../../../src/api/contract";
import { isWorkflowExecutionActive } from "../../../src/features/run/run_execution_state";

function snapshot(status: string): RunSnapshot {
  return { run: { status } } as RunSnapshot;
}

test.each(["CREATED", "ANALYZING", "RETRIEVING", "PLANNING", "EXECUTING", "VERIFYING", "CANCEL_REQUESTED"])(
  "treats %s as active workflow execution",
  (status) => expect(isWorkflowExecutionActive(snapshot(status))).toBe(true),
);

test.each(["WAITING_CONFIRMATION", "WAITING_APPROVAL", "REAUTH_REQUIRED", "RECOVERY_REQUIRED", "COMPLETED", "FAILED", "BLOCKED", "CANCELLED"])(
  "treats %s as suspended or terminal workflow execution",
  (status) => expect(isWorkflowExecutionActive(snapshot(status))).toBe(false),
);
