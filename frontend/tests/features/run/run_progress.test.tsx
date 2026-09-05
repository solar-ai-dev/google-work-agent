import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { RunSnapshot } from "../../../src/api/contract";
import { RunProgress } from "../../../src/features/run/run_progress";
import type { RunSseEvent } from "../../../src/features/run/api/run_sse_event";

test("a newer snapshot makes the current state primary over a stale status event", () => {
  const snapshot = { run: { run_id: "run-1", version: 3, status: "WAITING_APPROVAL" }, terminal_result_kind: "NONE" } as RunSnapshot;
  const latestEvent = { schema_version: 1, event_id: "old", run_id: "run-1", action_id: null, occurred_at_ms: 1, event_type: "run_status", payload: { status: "ANALYZING", snapshot_version: 1 }, projection_version: 1 } as RunSseEvent;
  render(<RunProgress snapshot={snapshot} latestEvent={latestEvent} busy={null} onResume={vi.fn()} />);
  expect(screen.getByTestId("run-event-progress")).toHaveTextContent("실행 전 승인을 기다리고 있습니다.");
});

test("RunProgress exposes only the server-projected resume action", async () => {
  const snapshot = { run: { status: "BLOCKED", next_allowed_commands: ["REQUEST_CANCEL"] }, execution_status: { action_count: 1, terminal_action_count: 0 }, terminal_result_kind: "NONE", error: { actions: [{ kind: "RESUME_SAFE_CHECKPOINT", resume_kind: "SAFE_CHECKPOINT_RESUME" }] } } as RunSnapshot;
  const onResume = vi.fn();
  render(<RunProgress snapshot={snapshot} busy={null} onResume={onResume} />);
  await userEvent.setup().click(screen.getByRole("button", { name: "재개" }));
  expect(onResume).toHaveBeenCalledWith("SAFE_CHECKPOINT_RESUME");
});

test("RunProgress hides stale safe-resume actions while a run is active", () => {
  const snapshot = { run: { status: "ANALYZING", next_allowed_commands: ["REQUEST_CANCEL"] }, execution_status: { action_count: 0, terminal_action_count: 0 }, terminal_result_kind: "NONE", error: { actions: [{ kind: "RESUME_SAFE_CHECKPOINT", resume_kind: "SAFE_CHECKPOINT_RESUME" }] } } as RunSnapshot;
  render(<RunProgress snapshot={snapshot} busy={null} onResume={vi.fn()} />);
  expect(screen.queryByRole("button", { name: "재개" })).not.toBeInTheDocument();
});

test.each([
  ["tool_routing", { route_revision: 1, input_route_count: 2, output_mode: "ACTION" }, "도구 경로 에이전트 · 사용할 경로 2개를 정했습니다."],
  ["retrieval_progress", { coverage: "PARTIAL", completed_sources: 1, total_sources: 3 }, "자료 검색 에이전트 · 컨텍스트 1/3개를 확인하고 있습니다."],
  ["analysis_progress", { completed_stage: "WORK_ANALYSIS" }, "업무 분석 에이전트 · 필요한 조건과 근거를 정리했습니다."],
] as const)("RunProgress preserves canonical %s progress", (eventType, payload, label) => {
  const snapshot = { run: { status: "ANALYZING", next_allowed_commands: [] }, execution_status: { action_count: 0, terminal_action_count: 0 }, terminal_result_kind: "NONE" } as RunSnapshot;
  const latestEvent = {
    schema_version: 1, event_id: "event-1", run_id: "run-1", action_id: null,
    occurred_at_ms: 1, event_type: eventType, payload, projection_version: 1,
  } as RunSseEvent;
  render(<RunProgress snapshot={snapshot} latestEvent={latestEvent} busy={null} onResume={vi.fn()} />);
  expect(screen.getByTestId("run-event-progress")).toHaveTextContent(label);
});

test("RunProgress appends a gray line when the active agent stage changes", () => {
  const snapshot = { run: { run_id: "run-1", version: 1, status: "ANALYZING", next_allowed_commands: [] }, execution_status: { action_count: 0, terminal_action_count: 0 }, terminal_result_kind: "NONE" } as RunSnapshot;
  const first = { schema_version: 1, event_id: "event-1", run_id: "run-1", action_id: null, occurred_at_ms: 1, event_type: "phase_changed", payload: { phase: "REQUEST_ANALYSIS" }, projection_version: 1 } as RunSseEvent;
  const second = { ...first, event_id: "event-2", event_type: "phase_changed", payload: { phase: "TOOL_ROUTING" }, projection_version: 2 } as RunSseEvent;
  const rendered = render(<RunProgress snapshot={snapshot} latestEvent={first} busy={null} onResume={vi.fn()} />);
  rendered.rerender(<RunProgress snapshot={snapshot} latestEvent={second} busy={null} onResume={vi.fn()} />);
  expect(screen.getByText("요청 이해 에이전트 · 요청의 목적을 파악하고 있습니다.")).toBeInTheDocument();
  expect(screen.getByText("도구 경로 에이전트 · 사용할 도구를 정하고 있습니다.")).toBeInTheDocument();
});
