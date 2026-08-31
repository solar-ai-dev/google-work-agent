import type { RunSnapshot } from "../../api/contract";

export function ExecutionStatusCard({ snapshot }: { snapshot: RunSnapshot }): JSX.Element {
  return (
    <article className="info-card">
      <strong>실행 및 검증 상태</strong>
      {snapshot.actions.map((action) => (
        <div className="inline-row" key={action.action_id} style={{ justifyContent: "space-between" }}>
          <span>{action.tool_name}</span><span className="pill">{action.status}</span>
          {action.delivery_certainty ? <span className="muted">{action.delivery_certainty}</span> : null}
        </div>
      ))}
      <div className="muted">Verified {snapshot.verification_summary.verified_count}</div>
      <div className="muted">Mismatch {snapshot.verification_summary.mismatch_count}</div>
      {snapshot.recovery_summary.unknown_result_action_count > 0 ? (
        <p className="status-warn">결과 불명 작업 {snapshot.recovery_summary.unknown_result_action_count}건을 확인하고 있습니다.</p>
      ) : null}
    </article>
  );
}
