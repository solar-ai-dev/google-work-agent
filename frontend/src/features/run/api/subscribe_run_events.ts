import type { EventEnvelope } from "../../../api/contract";

export type RunEventHandlers = {
  onEvent: (event: EventEnvelope) => void;
  onSnapshotRequired: () => void;
  onStateChange: (message: string) => void;
};

export function subscribeRunEvents(runId: string, handlers: RunEventHandlers): () => void {
  const eventSource = new EventSource(`/api/v1/runs/${encodeURIComponent(runId)}/events`, { withCredentials: true });
  const seen = new Set<string>();
  eventSource.onopen = () => handlers.onStateChange("실시간 상태가 연결되었습니다.");
  eventSource.onerror = () => handlers.onStateChange("실시간 연결을 다시 시도하고 있습니다.");
  for (const eventType of ["run_status", "phase_changed", "confirmation_required", "plan_updated", "approval_required", "action_status", "verification_result", "reauth_required", "recovery_required", "EXTERNAL_LLM_SCOPE_PUBLISHED", "completed", "error", "snapshot_required"]) {
    eventSource.addEventListener(eventType, (event) => {
      const messageEvent = event as MessageEvent<string>;
      if (messageEvent.lastEventId && seen.has(messageEvent.lastEventId)) return;
      if (messageEvent.lastEventId) seen.add(messageEvent.lastEventId);
      if (eventType === "snapshot_required") {
        eventSource.close();
        handlers.onSnapshotRequired();
        return;
      }
      handlers.onEvent({ eventId: messageEvent.lastEventId, eventType, payload: JSON.parse(messageEvent.data) as Record<string, unknown> });
    });
  }
  return () => eventSource.close();
}
