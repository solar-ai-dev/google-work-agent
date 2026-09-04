import { describe, expect, test, vi } from "vitest";
import { subscribeRunEvents } from "../../../../src/features/run/api/subscribe_run_events";
import { RUN_SSE_EVENT_TYPES, type RunSseEventType } from "../../../../src/features/run/api/run_sse_event";

const payloads: Record<RunSseEventType, Record<string, unknown>> = {
  run_status: { status: "ANALYZING", snapshot_version: 2 },
  phase_changed: { phase: "TOOL_ROUTING" },
  tool_routing: { route_revision: 1, input_route_count: 2, output_mode: "ACTION" },
  retrieval_progress: { coverage: "PARTIAL", completed_sources: 1, total_sources: 2 },
  confirmation_required: { interrupt_id: "i-1", question: "계속할까요?", options: ["예"] },
  analysis_progress: { completed_stage: "WORK_ANALYSIS" },
  plan_updated: { plan_id: "p-1", revision_no: 2 },
  approval_required: { action_ids: ["a-1"] },
  action_status: { action_id: "a-1", status: "APPROVED" },
  verification_result: { action_id: "a-1", outcome: "VERIFIED" },
  reauth_required: { connector_id: "google" },
  recovery_required: { recovery: { reason_code: "CHECKPOINT_MISMATCH", message: "저장된 진행 위치를 다시 확인해야 합니다.", target: { target_kind: "RUN" }, allowed_resolution_kinds: ["RECHECK", "CANCEL", "FAIL"] } },
  completed: { status: "COMPLETED", result_kind: "SUCCESS" },
  error: { error_code: "INTERNAL_ERROR", recoverable: false },
};

class FakeEventSource {
  listeners = new Map<string, Array<(event: MessageEvent<string>) => void>>();
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  constructor(public readonly url: string, public readonly init?: EventSourceInit) {}
  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  emit(type: string, payload: unknown, eventId = `${type}-1`): void {
    const data = type === "snapshot_required" ? payload : {
      schema_version: 1, event_id: eventId, run_id: "run-1", action_id: null,
      occurred_at_ms: 1, event_type: type, payload, projection_version: 1,
    };
    const event = { data: JSON.stringify(data), lastEventId: eventId } as MessageEvent<string>;
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
  emitRaw(type: string, data: unknown, eventId = `${type}-1`): void {
    const event = { data: JSON.stringify(data), lastEventId: eventId } as MessageEvent<string>;
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

function setup() {
  let current: FakeEventSource | null = null;
  Object.defineProperty(globalThis, "EventSource", { configurable: true, value: vi.fn((url: string, init?: EventSourceInit) => (current = new FakeEventSource(url, init))) });
  const onEvent = vi.fn();
  const onSnapshotRequired = vi.fn();
  const onStateChange = vi.fn();
  const unsubscribe = subscribeRunEvents("run/1", { onEvent, onSnapshotRequired, onStateChange });
  return { current: () => current!, onEvent, onSnapshotRequired, onStateChange, unsubscribe };
}

describe("subscribeRunEvents", () => {
  test("declares, decodes, and dispatches the exact canonical 14-event set", () => {
    const context = setup();
    expect(RUN_SSE_EVENT_TYPES).toHaveLength(14);
    expect(context.current().listeners.size).toBe(15);
    for (const eventType of RUN_SSE_EVENT_TYPES) context.current().emit(eventType, payloads[eventType]);
    expect(context.onEvent).toHaveBeenCalledTimes(14);
    expect(context.onEvent.mock.calls.map(([event]) => event.event_type)).toEqual(RUN_SSE_EVENT_TYPES);
    context.unsubscribe();
  });

  test("observes unique events and closes before requesting a durable snapshot", () => {
    const context = setup();
    expect(context.current().url).toBe("/api/v1/runs/run%2F1/events");
    context.current().emit("plan_updated", payloads.plan_updated, "event-1");
    context.current().emit("plan_updated", payloads.plan_updated, "event-1");
    expect(context.onEvent).toHaveBeenCalledTimes(1);
    context.current().emit("snapshot_required", {}, "");
    expect(context.current().close).toHaveBeenCalled();
    expect(context.onSnapshotRequired).toHaveBeenCalledOnce();
  });

  test.each(["RUN_UPDATED", "EXTERNAL_LLM_SCOPE_PUBLISHED", "unknown"])("does not accept non-SSE event %s", (eventType) => {
    const context = setup();
    context.current().emit(eventType, {});
    expect(context.onEvent).not.toHaveBeenCalled();
  });

  test("rejects mismatched, undeclared, and malformed envelopes without trusted-state dispatch", () => {
    const context = setup();
    context.current().emit("run_status", payloads.phase_changed, "bad-1");
    context.current().emit("run_status", { ...payloads.run_status, token: "secret" }, "bad-2");
    context.current().emitRaw("run_status", { schema_version: 1 }, "bad-3");
    expect(context.onEvent).not.toHaveBeenCalled();
    expect(context.onStateChange).toHaveBeenCalledTimes(3);
  });
});
