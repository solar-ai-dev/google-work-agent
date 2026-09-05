import { useEffect, useState } from "react";
import type { RunSnapshot } from "../../api/contract";
import type { RunSseEvent } from "./api/run_sse_event";

type ActivityLine = { eventId: string; label: string };

export function RunProgress({ snapshot, latestEvent = null, busy, onResume }: {
  snapshot: RunSnapshot;
  latestEvent?: RunSseEvent | null;
  busy: string | null;
  onResume: (resumeKind: "SAFE_CHECKPOINT_RESUME") => void;
}): JSX.Element {
  const [activity, setActivity] = useState<{ runId: string; lines: ActivityLine[] }>({ runId: snapshot.run.run_id, lines: [] });
  const manuallyResumable = ["RECOVERY_REQUIRED", "FAILED", "BLOCKED"].includes(snapshot.run.status);
  const resumeAction = manuallyResumable
    ? snapshot.error?.actions.find(
        (action) => action.kind === "RESUME_SAFE_CHECKPOINT" && action.resume_kind === "SAFE_CHECKPOINT_RESUME",
      )
    : undefined;
  useEffect(() => {
    if (!latestEvent) return;
    const label = eventProgressLabel(latestEvent);
    if (!label) return;
    setActivity((current) => {
      const lines = current.runId === snapshot.run.run_id ? current.lines : [];
      if (lines.some((line) => line.eventId === latestEvent.event_id)) return { runId: snapshot.run.run_id, lines };
      return { runId: snapshot.run.run_id, lines: [...lines, { eventId: latestEvent.event_id, label }].slice(-12) };
    });
  }, [latestEvent, snapshot.run.run_id]);
  const recordedLines = activity.runId === snapshot.run.run_id && activity.lines.length > 0
    ? activity.lines
    : [{ eventId: `snapshot-${snapshot.run.version}`, label: statusProgressLabel(snapshot.run.status) }];
  const hasOlderStatusEvent = latestEvent?.event_type === "run_status"
    && latestEvent.payload.snapshot_version < snapshot.run.version;
  const lines = hasOlderStatusEvent
    ? [...recordedLines, { eventId: `current-${snapshot.run.version}`, label: statusProgressLabel(snapshot.run.status) }]
    : recordedLines;
  const activelyWorking = ["CREATED", "ANALYZING", "RETRIEVING", "PLANNING", "EXECUTING", "VERIFYING"].includes(snapshot.run.status);
  return (
    <section className="agent-progress" aria-label="에이전트 진행">
      <div className="agent-progress-lines" aria-live="polite">
        {lines.map((line, index) => <p className={`agent-status-line${activelyWorking && index === lines.length - 1 ? " agent-status-line--active" : ""}`} data-testid={index === lines.length - 1 ? "run-event-progress" : undefined} key={line.eventId}>{line.label}</p>)}
        {snapshot.run.status === "FAILED" ? <p className="status-warn">작업을 완료하지 못했습니다.</p> : null}
        {snapshot.terminal_result_kind === "PARTIAL" ? <p className="status-warn">일부 작업은 완료되었고 나머지는 취소되었습니다.</p> : null}
      </div>
      <div className="button-row">
        {resumeAction ? (
          <button className="button-secondary" type="button" disabled={busy === "resume-run"} onClick={() => onResume(resumeAction.resume_kind!)}>재개</button>
        ) : null}
      </div>
    </section>
  );
}

function eventProgressLabel(event: RunSseEvent): string | null {
  switch (event.event_type) {
    case "run_status": return statusProgressLabel(event.payload.status);
    case "phase_changed": return phaseProgressLabel(event.payload.phase);
    case "tool_routing": return `도구 경로 에이전트 · 사용할 경로 ${event.payload.input_route_count}개를 정했습니다.`;
    case "retrieval_progress": return `자료 검색 에이전트 · 컨텍스트 ${event.payload.completed_sources}/${event.payload.total_sources}개를 확인하고 있습니다.`;
    case "confirmation_required": return "메인 에이전트 · 요청을 정확히 이해하기 위해 답변을 기다리고 있습니다.";
    case "analysis_progress": return "업무 분석 에이전트 · 필요한 조건과 근거를 정리했습니다.";
    case "plan_updated": return "계획 에이전트 · 실행할 내용을 작성했습니다.";
    case "approval_required": return "메인 에이전트 · 실행 전 승인을 기다리고 있습니다.";
    case "action_status": return actionProgressLabel(event.payload.status);
    case "verification_result": return event.payload.outcome === "VERIFIED" ? "검증 에이전트 · 실행 결과를 확인했습니다." : "검증 에이전트 · 요청 내용과 다른 결과를 확인했습니다.";
    case "reauth_required": return "메인 에이전트 · Google 계정 재연결을 기다리고 있습니다.";
    case "recovery_required": return "복구 에이전트 · 안전하게 계속할 방법을 확인하고 있습니다.";
    case "completed": return event.payload.status === "COMPLETED" ? "메인 에이전트 · 작업을 완료했습니다." : "메인 에이전트 · 작업을 종료했습니다.";
    case "error": return "메인 에이전트 · 작업을 계속할 수 없는 문제를 확인했습니다.";
  }
}

function phaseProgressLabel(phase: string): string {
  return ({
    INITIALIZE: "메인 에이전트 · 작업을 준비하고 있습니다.",
    REQUEST_ANALYSIS: "요청 이해 에이전트 · 요청의 목적을 파악하고 있습니다.",
    TOOL_ROUTING: "도구 경로 에이전트 · 사용할 도구를 정하고 있습니다.",
    WAITING_CONFIRMATION: "메인 에이전트 · 추가 답변을 기다리고 있습니다.",
    CONTEXT_RETRIEVAL: "자료 검색 에이전트 · 필요한 컨텍스트를 찾고 있습니다.",
    WORK_ANALYSIS: "업무 분석 에이전트 · 근거와 조건을 검토하고 있습니다.",
    SOLUTION_PLANNING: "계획 에이전트 · 실행할 내용을 작성하고 있습니다.",
    PLAN_REVIEW: "검토 에이전트 · 실행 계획을 확인하고 있습니다.",
    DOMAIN_VALIDATION: "검토 에이전트 · 안전하게 실행할 수 있는지 확인하고 있습니다.",
    WAITING_APPROVAL: "메인 에이전트 · 실행 전 승인을 기다리고 있습니다.",
    PREFLIGHT: "실행 에이전트 · 승인 내용과 실행 조건을 다시 확인하고 있습니다.",
    ACTION_EXECUTION: "실행 에이전트 · 승인된 작업을 실행하고 있습니다.",
    READ_EXECUTION: "자료 검색 에이전트 · 요청한 자료를 읽고 있습니다.",
    VERIFICATION: "검증 에이전트 · Google에서 결과를 다시 확인하고 있습니다.",
    RESPONSE_SYNTHESIS: "메인 에이전트 · 답변을 정리하고 있습니다.",
    RECOVERY: "복구 에이전트 · 안전하게 계속할 방법을 확인하고 있습니다.",
    FINALIZE: "메인 에이전트 · 결과를 마무리하고 있습니다.",
  } as Record<string, string>)[phase] ?? "메인 에이전트 · 작업을 처리하고 있습니다.";
}

function statusProgressLabel(status: string): string {
  return ({
    CREATED: "메인 에이전트 · 작업을 준비하고 있습니다.",
    ANALYZING: "업무 분석 에이전트 · 요청을 분석하고 있습니다.",
    RETRIEVING: "자료 검색 에이전트 · 필요한 컨텍스트를 찾고 있습니다.",
    WAITING_CONFIRMATION: "메인 에이전트 · 추가 답변을 기다리고 있습니다.",
    PLANNING: "계획 에이전트 · 실행할 내용을 작성하고 있습니다.",
    WAITING_APPROVAL: "메인 에이전트 · 실행 전 승인을 기다리고 있습니다.",
    EXECUTING: "실행 에이전트 · 승인된 작업을 실행하고 있습니다.",
    VERIFYING: "검증 에이전트 · Google에서 결과를 다시 확인하고 있습니다.",
    COMPLETED: "메인 에이전트 · 작업을 완료했습니다.",
    CANCEL_REQUESTED: "메인 에이전트 · 안전하게 중단하고 있습니다.",
    CANCELLED: "메인 에이전트 · 작업을 취소했습니다.",
    REAUTH_REQUIRED: "메인 에이전트 · Google 계정 재연결을 기다리고 있습니다.",
    RECOVERY_REQUIRED: "복구 에이전트 · 다음 진행 방법을 기다리고 있습니다.",
    FAILED: "메인 에이전트 · 작업을 완료하지 못했습니다.",
    BLOCKED: "메인 에이전트 · 안전을 위해 작업을 중단했습니다.",
  } as Record<string, string>)[status] ?? "메인 에이전트 · 작업을 처리하고 있습니다.";
}

function actionProgressLabel(status: string): string {
  return ({
    PROPOSED: "계획 에이전트 · 실행할 작업을 제안했습니다.",
    MODIFIED: "계획 에이전트 · 요청대로 실행 내용을 바꿨습니다.",
    APPROVED: "실행 에이전트 · 승인을 확인했습니다.",
    REJECTED: "메인 에이전트 · 실행하지 않기로 한 작업을 제외했습니다.",
    EXPIRED: "메인 에이전트 · 승인 시간이 지나 다시 확인이 필요합니다.",
    EXECUTING: "실행 에이전트 · 승인된 작업을 실행하고 있습니다.",
    UNKNOWN_RESULT: "복구 에이전트 · 실제 실행 결과를 확인하고 있습니다.",
    EXECUTED: "실행 에이전트 · 실행을 마치고 결과를 확인하고 있습니다.",
    VERIFIED: "검증 에이전트 · 실행 결과를 확인했습니다.",
    FAILED: "실행 에이전트 · 작업을 완료하지 못했습니다.",
    BLOCKED: "메인 에이전트 · 안전을 위해 작업을 실행하지 않았습니다.",
    DEPENDENCY_BLOCKED: "메인 에이전트 · 먼저 필요한 작업이 없어 실행하지 않았습니다.",
    MISMATCH: "검증 에이전트 · 요청 내용과 다른 결과를 확인했습니다.",
    CANCELLED: "메인 에이전트 · 작업을 취소했습니다.",
  } as Record<string, string>)[status] ?? "메인 에이전트 · 작업 상태를 확인하고 있습니다.";
}
