import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { RunSnapshot } from "../../../src/api/contract";
import { useRunProjection } from "../../../src/features/run/use_run_projection";
import { getRunSnapshot, getRunContext } from "../../../src/features/run/api/get_run_snapshot";

vi.mock("../../../src/features/run/api/get_run_snapshot", () => ({ getRunSnapshot: vi.fn(), getRunContext: vi.fn() }));
vi.mock("../../../src/features/run/api/subscribe_run_events", () => ({ subscribeRunEvents: vi.fn(() => vi.fn()) }));
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks(); });

function snapshot(status: RunSnapshot["run"]["status"], version: number): RunSnapshot {
  return { run: { run_id: "run", conversation_id: "conversation", status, version, finished_at_ms: null }, pending_interrupt: null } as RunSnapshot;
}

function options() {
  return {
    busyCommand: null, setBusyCommand: vi.fn(), commandIdFor: () => "command", completeCommand: vi.fn(),
    beginConversationProjection: () => 1,
    getConversationProjection: () => ({ conversationId: "conversation", generation: 1 }),
    isCurrentProjection: () => true, reloadConversationHistory: vi.fn(async () => undefined),
    selectConversationHistory: vi.fn(async () => undefined), isRunHistorySynced: () => false,
    markRunHistorySynced: vi.fn(), onStatusLine: vi.fn(),
  };
}

test("active runs reconcile approval snapshots without an SSE event and stop polling when suspended", async () => {
  vi.useFakeTimers();
  vi.mocked(getRunContext).mockResolvedValue({ context: null } as never);
  vi.mocked(getRunSnapshot).mockResolvedValueOnce(snapshot("ANALYZING", 1)).mockResolvedValue(snapshot("WAITING_APPROVAL", 3));
  const { result } = renderHook(() => useRunProjection(options()));
  await act(async () => { await result.current.selectRun("run"); });
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  expect(result.current.runSnapshot?.run.status).toBe("WAITING_APPROVAL");
  await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
  expect(getRunSnapshot).toHaveBeenCalledTimes(2);
});

test("a late older snapshot cannot replace newer approval state", async () => {
  vi.mocked(getRunContext).mockResolvedValue({ context: null } as never);
  vi.mocked(getRunSnapshot).mockResolvedValueOnce(snapshot("WAITING_APPROVAL", 3)).mockResolvedValueOnce(snapshot("ANALYZING", 1));
  const { result } = renderHook(() => useRunProjection(options()));
  await act(async () => { await result.current.refreshRun("run"); });
  await act(async () => { await result.current.refreshRun("run"); });
  expect(result.current.runSnapshot?.run.status).toBe("WAITING_APPROVAL");
});
