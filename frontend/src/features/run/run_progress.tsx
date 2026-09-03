import type { RunSnapshot } from "../../api/contract";
import type { RunSseEvent } from "./api/run_sse_event";

export function RunProgress({ snapshot, latestEvent = null, busy, onCancel, onResume }: {
  snapshot: RunSnapshot;
  latestEvent?: RunSseEvent | null;
  busy: string | null;
  onCancel: () => void;
  onResume: (resumeKind: "SAFE_CHECKPOINT_RESUME") => void;
}): JSX.Element {
  const resumeAction = snapshot.error?.actions.find(
    (action) => action.kind === "RESUME_SAFE_CHECKPOINT" && action.resume_kind === "SAFE_CHECKPOINT_RESUME",
  );
  const eventLabel = latestEvent ? eventProgressLabel(latestEvent) : null;
  return (
    <div className={`panel-header run-header${snapshot.run.status === "FAILED" ? " run-header--failed" : ""}`}>
      <div>
        <strong>{snapshot.run.status === "FAILED" ? "실행 실패" : "실행 진행"}</strong>
        <div className="muted">{statusLabel(snapshot.run.status)}</div>
        <div className="muted">
          작업 {snapshot.execution_status.terminal_action_count}/{snapshot.execution_status.action_count}
        </div>
        {eventLabel ? <div className="muted" data-testid="run-event-progress">{eventLabel}</div> : null}
        {snapshot.run.status === "FAILED" ? <div className="status-warn">작업을 완료하지 못했습니다.</div> : null}
        {snapshot.terminal_result_kind === "PARTIAL" ? <div className="status-warn">일부 작업은 완료되었고 나머지는 취소되었습니다.</div> : null}
      </div>
      <div className="button-row">
        {snapshot.run.next_allowed_commands.includes("REQUEST_CANCEL") ? (
          <button className="button-danger" type="button" disabled={busy === "cancel-run"} onClick={onCancel}>취소</button>
        ) : null}
        {resumeAction ? (
          <button className="button-secondary" type="button" disabled={busy === "resume-run"} onClick={() => onResume(resumeAction.resume_kind!)}>재개</button>
        ) : null}
      </div>
    </div>
  );
}

function eventProgressLabel(event: RunSseEvent): string | null {
  switch (event.event_type) {
    case "tool_routing": return `도구 경로 ${event.payload.input_route_count}개 분석 완료`;
    case "retrieval_progress": return `자료 확인 ${event.payload.completed_sources}/${event.payload.total_sources}`;
    case "analysis_progress": return `분석 완료: ${event.payload.completed_stage}`;
    default: return null;
  }
}

function statusLabel(status: string): string {
  return ({ SINGLE: "작업을 처리하고 있습니다.", WAITING_APPROVAL: "승인이 필요합니다.", EXECUTING: "작업을 처리하고 있습니다.", WAITING_CONFIRMATION: "추가 확인이 필요합니다.", RECOVERY_REQUIRED: "복구 결정을 기다리고 있습니다.", COMPLETED: "작업을 완료했습니다.", CANCELLED: "작업을 취소했습니다." } as Record<string, string>)[status] ?? status;
}
