import { useState } from "react";
import type { ApprovalSnapshot, RunAction, RunSnapshot } from "../../api/contract";
import { calendarConflictDecision, feasibilityDecision, hasOtherRisk, taskDuplicateDecision } from "./risk_presentation";

export function ActionPlanCard({ snapshot, busy, retryActionIds, formatTime, onApprove, onModify, onReject, onRetry, onAttachFiles }: {
  snapshot: RunSnapshot;
  busy: string | null;
  retryActionIds: ReadonlySet<string>;
  formatTime: (value: number) => string;
  onApprove: (action: RunAction, acknowledgements: ReadonlySet<string>) => void;
  onModify: (action: RunAction, patch: Record<string, unknown>) => void;
  onReject: (action: RunAction) => void;
  onRetry: (action: RunAction) => void;
  onAttachFiles: (action: RunAction, files: FileList) => void;
}): JSX.Element | null {
  if (!snapshot.current_plan) return null;
  return (
    <section aria-label="Action Plan">
      <article className="info-card"><strong>Action Plan</strong><div className="muted">{snapshot.current_plan.summary_text ?? "요약이 없습니다."}</div></article>
      {snapshot.actions.map((action) => (
        <ActionDecisionCard key={action.action_id} action={action} approval={snapshot.approvals.find((item) => item.action_id === action.action_id)} busy={busy} canRetry={retryActionIds.has(action.action_id)} formatTime={formatTime} onApprove={onApprove} onModify={onModify} onReject={onReject} onRetry={onRetry} onAttachFiles={onAttachFiles} />
      ))}
    </section>
  );
}

function ActionDecisionCard({ action, approval, busy, canRetry, formatTime, onApprove, onModify, onReject, onRetry, onAttachFiles }: {
  action: RunAction; approval?: ApprovalSnapshot; busy: string | null; canRetry: boolean; formatTime: (value: number) => string;
  onApprove: (action: RunAction, acknowledgements: ReadonlySet<string>) => void; onModify: (action: RunAction, patch: Record<string, unknown>) => void; onReject: (action: RunAction) => void; onRetry: (action: RunAction) => void; onAttachFiles: (action: RunAction, files: FileList) => void;
}): JSX.Element {
  const [acknowledgements, setAcknowledgements] = useState<Set<string>>(new Set());
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const requiredAcknowledgements = action.required_acknowledgements ?? [];
  const editableFields = action.editable_fields ?? [];
  const patch = Object.fromEntries(Object.entries(editValues).filter(([, value]) => value.trim()).map(([key, value]) => [key, value.trim()]));
  const duplicate = taskDuplicateDecision(action.risk);
  const conflict = calendarConflictDecision(action.risk);
  const feasibility = feasibilityDecision(action.risk);
  return (
    <article className="info-card">
      <div className="inline-row"><strong>{action.tool_name}</strong></div>
      <div className="muted">{action.effect_type} / {action.verification_policy}</div>
      {duplicate === "SIMILAR_CANDIDATE" ? <p className="status-warn">비슷한 기존 작업이 있습니다.</p> : null}
      {duplicate === "CLEAR_DUPLICATE" ? <p className="status-warn">동일한 작업이 이미 있습니다.</p> : null}
      {conflict === "WARNING" ? <p className="status-warn">겹칠 가능성이 있거나 업무 시간 밖의 일정입니다.</p> : null}
      {conflict === "HARD_CONFLICT" ? <p className="status-warn">해당 시간에 기존 일정이 있습니다.</p> : null}
      {feasibility === "RISK" ? <p className="status-warn">현재 일정 기준으로 가능한 시간이 제한적입니다.</p> : null}
      {feasibility === "INFEASIBLE" ? <p className="status-warn">현재 업무 시간과 일정 기준으로 마감 전에 필요한 연속 시간을 확보할 수 없습니다.</p> : null}
      {hasOtherRisk(action.risk) ? <p className="status-warn">서버 검증에서 확인된 위험 정보가 있습니다. 승인 전에 확인해 주세요.</p> : null}
      <details><summary>승인 상세</summary><dl className="metadata-list"><div><dt>Action</dt><dd>{action.tool_name}</dd></div><div><dt>검증</dt><dd>{action.verification_policy}</dd></div></dl></details>
      {approval ? <div className="muted">승인 상태 {approval.status} / 만료 {formatTime(approval.expires_at_ms)}</div> : null}
      {requiredAcknowledgements.map((item) => (
        <label key={item}><input type="checkbox" checked={acknowledgements.has(item)} onChange={(event) => setAcknowledgements((current) => { const next = new Set(current); if (event.target.checked) next.add(item); else next.delete(item); return next; })} /> {item === "TASK_DUPLICATE" ? "중복 가능성을 확인했습니다." : "일정 충돌 가능성을 확인했습니다."}</label>
      ))}
      {action.next_allowed_commands.includes("MODIFY_ACTION") && editableFields.some((field) => field !== "attachments") ? (
        <fieldset><legend>수정</legend>{editableFields.filter((field) => field !== "attachments").map((field) => <label key={field}>{field}<input value={editValues[field] ?? ""} onChange={(event) => setEditValues((current) => ({ ...current, [field]: event.target.value }))} /></label>)}<button className="button-secondary" type="button" disabled={busy === `modify-${action.action_id}` || Object.keys(patch).length === 0} onClick={() => onModify(action, patch)}>수정</button></fieldset>
      ) : null}
      {action.attachment_allowed ? <label className="button-secondary">첨부파일 선택<input type="file" multiple hidden disabled={busy === `modify-${action.action_id}`} onChange={(event) => { if (event.currentTarget.files) onAttachFiles(action, event.currentTarget.files); event.currentTarget.value = ""; }} /></label> : null}
      <div className="button-row">
        {action.next_allowed_commands.includes("APPROVE_ACTION") ? <button className="button-primary" type="button" disabled={busy === `approve-${action.action_id}`} onClick={() => onApprove(action, requiredAcknowledgements.length ? new Set(requiredAcknowledgements) : acknowledgements)}>{approvalLabel(duplicate, conflict)}</button> : null}
        {action.next_allowed_commands.includes("REJECT_ACTION") ? <button className="button-danger" type="button" disabled={busy === `reject-${action.action_id}`} onClick={() => onReject(action)}>거절</button> : null}
        {canRetry ? <button className="button-secondary" type="button" disabled={busy === `retry-${action.action_id}`} onClick={() => onRetry(action)}>다시 준비</button> : null}
      </div>
      {action.status === "UNKNOWN_RESULT" ? <p className="status-warn">실제 결과를 확인하는 중입니다. 새 쓰기 실행은 잠시 막혀 있습니다.</p> : null}
    </article>
  );
}

function approvalLabel(duplicate: ReturnType<typeof taskDuplicateDecision>, conflict: ReturnType<typeof calendarConflictDecision>): string {
  if (conflict === "HARD_CONFLICT") return "충돌을 알고도 진행";
  if (duplicate === "CLEAR_DUPLICATE") return "그래도 새로 만들기";
  if (conflict === "WARNING" || duplicate === "SIMILAR_CANDIDATE") return "확인하고 승인";
  return "승인";
}
