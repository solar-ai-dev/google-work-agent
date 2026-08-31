import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import type { RunSnapshot } from "../../../src/api/contract";
import { ExecutionStatusCard } from "../../../src/features/run/execution_status_card";

test("ExecutionStatusCard keeps UNKNOWN_RESULT non-terminal", () => {
  const snapshot = { actions: [{ action_id: "a-1", tool_name: "gmail_send", status: "UNKNOWN_RESULT", delivery_certainty: "SENT_RESPONSE_LOST" }], verification_summary: { verified_count: 0, mismatch_count: 0 }, recovery_summary: { unknown_result_action_count: 1 } } as RunSnapshot;
  render(<ExecutionStatusCard snapshot={snapshot} />);
  expect(screen.getByText("UNKNOWN_RESULT")).toBeInTheDocument();
  expect(screen.getByText("SENT_RESPONSE_LOST")).toBeInTheDocument();
  expect(screen.queryByText(/성공 또는 실패/)).not.toBeInTheDocument();
});
