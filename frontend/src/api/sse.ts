import type { EventEnvelope } from "./contract";

export type SseHandlers = {
  onEvent: (event: EventEnvelope) => void;
  onStateChange: (message: string) => void;
};

export function subscribeRunEvents(runId: string, handlers: SseHandlers): () => void {
  const eventSource = new EventSource(`/api/v1/runs/${encodeURIComponent(runId)}/events`, {
    withCredentials: true,
  });
  const seen = new Set<string>();

  eventSource.onopen = () => handlers.onStateChange("실시간 상태가 연결되었습니다.");
  eventSource.onerror = () => handlers.onStateChange("실시간 연결을 다시 시도하고 있습니다.");
  const eventTypes = [
    "run_status",
    "phase_changed",
    "confirmation_required",
    "plan_updated",
    "approval_required",
    "action_status",
    "verification_result",
    "reauth_required",
    "recovery_required",
    "completed",
    "error",
    "snapshot_required",
  ];
  for (const eventType of eventTypes) {
    eventSource.addEventListener(eventType, (event) => {
      const messageEvent = event as MessageEvent<string>;
      if (seen.has(messageEvent.lastEventId)) {
        return;
      }
      seen.add(messageEvent.lastEventId);
      handlers.onEvent({
        eventId: messageEvent.lastEventId,
        eventType,
        payload: JSON.parse(messageEvent.data) as Record<string, unknown>,
      });
    });
  }
  return () => {
    eventSource.close();
  };
}
