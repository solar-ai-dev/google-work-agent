import { describe, expect, test, vi } from "vitest";
import { subscribeRunEvents } from "./sse";

class FakeEventSource {
  listeners = new Map<string, Array<(event: MessageEvent<string>) => void>>();
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();

  constructor(public readonly url: string, public readonly init?: EventSourceInit) {}

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void {
    const current = this.listeners.get(type) ?? [];
    current.push(listener);
    this.listeners.set(type, current);
  }

  emit(type: string, payload: Record<string, unknown>, eventId = `${type}-1`): void {
    const event = { data: JSON.stringify(payload), lastEventId: eventId } as MessageEvent<string>;
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event);
    }
  }
}

describe("subscribeRunEvents", () => {
  test("subscribes with credentials, deduplicates events, and unsubscribes", () => {
    const instances: FakeEventSource[] = [];
    Object.defineProperty(globalThis, "EventSource", {
      configurable: true,
      value: vi.fn((url: string, init?: EventSourceInit) => {
        const created = new FakeEventSource(url, init);
        instances.push(created);
        return created;
      }),
    });

    const onEvent = vi.fn();
    const onStateChange = vi.fn();
    const unsubscribe = subscribeRunEvents("run-1", { onEvent, onStateChange });

    const current = instances[0];
    if (!current) {
      throw new Error("event source was not created");
    }

    expect(current.url).toBe("/api/v1/runs/run-1/events");
    expect(current.init).toEqual({ withCredentials: true });

    current.onopen?.();
    current.onerror?.();
    current.emit("plan_updated", { revision: 1 }, "evt-1");
    current.emit("plan_updated", { revision: 2 }, "evt-1");

    expect(onStateChange).toHaveBeenNthCalledWith(1, "실시간 상태가 연결되었습니다.");
    expect(onStateChange).toHaveBeenNthCalledWith(2, "실시간 연결을 다시 시도하고 있습니다.");
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onEvent).toHaveBeenCalledWith({
      eventId: "evt-1",
      eventType: "plan_updated",
      payload: { revision: 1 },
    });

    unsubscribe();
    expect(current.close).toHaveBeenCalled();
  });
});
