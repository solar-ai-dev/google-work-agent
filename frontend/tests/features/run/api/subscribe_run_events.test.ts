import { describe, expect, test, vi } from "vitest";
import { subscribeRunEvents } from "../../../../src/features/run/api/subscribe_run_events";

class FakeEventSource {
  listeners = new Map<string, Array<(event: MessageEvent<string>) => void>>();
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  constructor(public readonly url: string, public readonly init?: EventSourceInit) {}
  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  emit(type: string, payload: Record<string, unknown>, eventId = `${type}-1`): void {
    const event = { data: JSON.stringify(payload), lastEventId: eventId } as MessageEvent<string>;
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

describe("subscribeRunEvents", () => {
  test("observes unique events and closes before requesting a durable snapshot", () => {
    let current: FakeEventSource | null = null;
    Object.defineProperty(globalThis, "EventSource", { configurable: true, value: vi.fn((url: string, init?: EventSourceInit) => (current = new FakeEventSource(url, init))) });
    const onEvent = vi.fn();
    const onSnapshotRequired = vi.fn();
    const unsubscribe = subscribeRunEvents("run/1", { onEvent, onSnapshotRequired, onStateChange: vi.fn() });
    expect(current!.url).toBe("/api/v1/runs/run%2F1/events");
    current!.emit("plan_updated", { revision: 1 }, "event-1");
    current!.emit("plan_updated", { revision: 2 }, "event-1");
    expect(onEvent).toHaveBeenCalledTimes(1);
    current!.emit("EXTERNAL_LLM_SCOPE_PUBLISHED", { scope_revision: 2 }, "event-2");
    expect(onEvent).toHaveBeenLastCalledWith(expect.objectContaining({ eventType: "EXTERNAL_LLM_SCOPE_PUBLISHED" }));
    current!.emit("snapshot_required", {}, "");
    expect(current!.close).toHaveBeenCalled();
    expect(onSnapshotRequired).toHaveBeenCalledOnce();
    unsubscribe();
  });
});
