import type { RunSnapshot } from "../../api/contract";

export function ExecutionStatusCard({ snapshot }: { snapshot: RunSnapshot }): JSX.Element {
  return (
    <section className="execution-conversation" aria-label="실행 및 검증 진행">
      {snapshot.actions.map((action) => (
        <p className={`agent-status-line${isActiveAction(action.status) ? " agent-status-line--active" : ""}`} data-action-status={action.status} key={action.action_id}>
          {agentLabel(action.tool_name)} · {actionStatusLabel(action.status, action.delivery_certainty)}
        </p>
      ))}
      {snapshot.verification_summary.verified_count > 0 ? <p className="agent-status-line">검증 에이전트 · {snapshot.verification_summary.verified_count}개 작업의 결과를 확인했습니다.</p> : null}
      {snapshot.verification_summary.mismatch_count > 0 ? <p className="agent-status-line status-warn">검증 에이전트 · {snapshot.verification_summary.mismatch_count}개 작업에서 요청과 다른 결과를 확인했습니다.</p> : null}
      {snapshot.recovery_summary.unknown_result_action_count > 0 ? (
        <p className="status-warn">결과 불명 작업 {snapshot.recovery_summary.unknown_result_action_count}건을 확인하고 있습니다.</p>
      ) : null}
    </section>
  );
}

function agentLabel(toolName: string): string {
  if (toolName.startsWith("gmail_")) return "Gmail 실행 에이전트";
  if (toolName.startsWith("tasks_")) return "Tasks 실행 에이전트";
  if (toolName.startsWith("calendar_")) return "Calendar 실행 에이전트";
  return "실행 에이전트";
}

function actionStatusLabel(status: string, deliveryCertainty: RunSnapshot["actions"][number]["delivery_certainty"]): string {
  if (status === "UNKNOWN_RESULT" && deliveryCertainty === "SENT_RESPONSE_LOST") return "응답을 받지 못해 실제 결과를 안전하게 확인하고 있습니다.";
  return ({
    PROPOSED: "실행 전 승인을 기다리고 있습니다.",
    MODIFIED: "바뀐 내용을 다시 확인하고 있습니다.",
    APPROVED: "승인을 확인하고 실행을 준비하고 있습니다.",
    REJECTED: "사용자 선택에 따라 실행하지 않았습니다.",
    EXPIRED: "승인 시간이 지나 다시 확인이 필요합니다.",
    EXECUTING: "승인된 작업을 실행하고 있습니다.",
    UNKNOWN_RESULT: "실제 결과를 안전하게 확인하고 있습니다.",
    EXECUTED: "실행을 마치고 Google에서 결과를 확인하고 있습니다.",
    VERIFIED: "실행 결과를 확인했습니다.",
    FAILED: "작업을 완료하지 못했습니다.",
    BLOCKED: "안전을 위해 작업을 실행하지 않았습니다.",
    DEPENDENCY_BLOCKED: "먼저 필요한 작업이 없어 실행하지 않았습니다.",
    MISMATCH: "요청 내용과 다른 결과를 확인했습니다.",
    CANCELLED: "작업을 취소했습니다.",
  } as Record<string, string>)[status] ?? "작업 상태를 확인하고 있습니다.";
}

function isActiveAction(status: string): boolean {
  return ["APPROVED", "EXECUTING", "UNKNOWN_RESULT", "EXECUTED"].includes(status);
}
