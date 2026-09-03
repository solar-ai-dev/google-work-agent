import { decodeRunSseEvent, RUN_SSE_EVENT_TYPES, type RunSseEvent } from "./run_sse_event";

export type RunEventHandlers = {
  onEvent: (event: RunSseEvent) => void;
  onSnapshotRequired: () => void;
  onStateChange: (message: string) => void;
};

export function subscribeRunEvents(runId: string, handlers: RunEventHandlers): () => void {
  const eventSource = new EventSource(`/api/v1/runs/${encodeURIComponent(runId)}/events`, { withCredentials: true });
  const seen = new Set<string>();
  eventSource.onopen = () => handlers.onStateChange("실시간 상태가 연결되었습니다.");
  eventSource.onerror = () => handlers.onStateChange("실시간 연결을 다시 시도하고 있습니다.");
  for (const eventType of RUN_SSE_EVENT_TYPES) {
    eventSource.addEventListener(eventType, (event) => {
      const messageEvent = event as MessageEvent<string>;
      try {
        const decoded = decodeRunSseEvent(messageEvent.data);
        if (decoded.event_type !== eventType || (messageEvent.lastEventId && decoded.event_id !== messageEvent.lastEventId)) throw new Error("SSE transport identity mismatch");
        if (messageEvent.lastEventId && seen.has(messageEvent.lastEventId)) return;
        if (messageEvent.lastEventId) seen.add(messageEvent.lastEventId);
        handlers.onEvent(decoded);
      } catch {
        handlers.onStateChange("실시간 이벤트 계약 오류가 감지되었습니다. 실행 상태를 새로 확인해 주세요.");
      }
    });
  }
  eventSource.addEventListener("snapshot_required", () => {
    eventSource.close();
    handlers.onSnapshotRequired();
  });
  return () => eventSource.close();
}
