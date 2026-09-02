import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { RunSnapshot } from "../../../src/api/contract";
import { RunProgress } from "../../../src/features/run/run_progress";
import type { RunSseEvent } from "../../../src/features/run/api/run_sse_event";

test("RunProgress exposes only server-projected cancel and resume actions", async () => {
  const snapshot = { run: { status: "BLOCKED", next_allowed_commands: ["REQUEST_CANCEL"] }, execution_status: { action_count: 1, terminal_action_count: 0 }, terminal_result_kind: "NONE", error: { actions: [{ kind: "RESUME_SAFE_CHECKPOINT", resume_kind: "SAFE_CHECKPOINT_RESUME" }] } } as RunSnapshot;
  const onResume = vi.fn();
  render(<RunProgress snapshot={snapshot} busy={null} onCancel={vi.fn()} onResume={onResume} />);
  await userEvent.setup().click(screen.getByRole("button", { name: "재개" }));
  expect(onResume).toHaveBeenCalledWith("SAFE_CHECKPOINT_RESUME");
});

test.each([
  ["tool_routing", { route_revision: 1, input_route_count: 2, output_mode: "ACTION" }, "도구 경로 2개 분석 완료"],
  ["retrieval_progress", { coverage: "PARTIAL", completed_sources: 1, total_sources: 3 }, "자료 확인 1/3"],
  ["analysis_progress", { completed_stage: "WORK_ANALYSIS" }, "분석 완료: WORK_ANALYSIS"],
] as const)("RunProgress preserves canonical %s progress", (eventType, payload, label) => {
  const snapshot = { run: { status: "ANALYZING", next_allowed_commands: [] }, execution_status: { action_count: 0, terminal_action_count: 0 }, terminal_result_kind: "NONE" } as RunSnapshot;
  const latestEvent = {
    schema_version: 1, event_id: "event-1", run_id: "run-1", action_id: null,
    occurred_at_ms: 1, event_type: eventType, payload, projection_version: 1,
  } as RunSseEvent;
  render(<RunProgress snapshot={snapshot} latestEvent={latestEvent} busy={null} onCancel={vi.fn()} onResume={vi.fn()} />);
  expect(screen.getByTestId("run-event-progress")).toHaveTextContent(label);
});
