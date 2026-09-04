import { useState } from "react";
import type { ApprovalSnapshot, RunAction, RunSnapshot } from "../../api/contract";
import { AttachmentPicker, type StagedAttachmentDescriptor } from "../attachment";
import { calendarConflictDecision, feasibilityDecision, hasOtherRisk, taskDuplicateDecision } from "./risk_presentation";

export function ActionPlanCard({ snapshot, busy, retryActionIds, formatTime, onApprove, onModify, onReject, onRetry, onAttachDescriptors }: {
  snapshot: RunSnapshot;
  busy: string | null;
  retryActionIds: ReadonlySet<string>;
  formatTime: (value: number) => string;
  onApprove: (action: RunAction, acknowledgements: ReadonlySet<string>) => void;
  onModify: (action: RunAction, patch: Record<string, unknown>) => void;
  onReject: (action: RunAction) => void;
  onRetry: (action: RunAction) => void;
  onAttachDescriptors: (action: RunAction, descriptors: StagedAttachmentDescriptor[]) => Promise<void> | void;
}): JSX.Element | null {
  if (!snapshot.current_plan || snapshot.actions.length === 0) return null;
  return (
    <section className="action-plan-conversation" aria-label="Action Plan">
      {snapshot.current_plan.summary_text ? <p className="agent-status-line">계획 에이전트 · {snapshot.current_plan.summary_text}</p> : null}
      {snapshot.actions.map((action) => (
        <ActionDecisionCard key={action.action_id} action={action} approval={snapshot.approvals.find((item) => item.action_id === action.action_id)} busy={busy} canRetry={retryActionIds.has(action.action_id)} formatTime={formatTime} onApprove={onApprove} onModify={onModify} onReject={onReject} onRetry={onRetry} onAttachDescriptors={onAttachDescriptors} />
      ))}
    </section>
  );
}

function ActionDecisionCard({ action, approval, busy, canRetry, formatTime, onApprove, onModify, onReject, onRetry, onAttachDescriptors }: {
  action: RunAction; approval?: ApprovalSnapshot; busy: string | null; canRetry: boolean; formatTime: (value: number) => string;
  onApprove: (action: RunAction, acknowledgements: ReadonlySet<string>) => void; onModify: (action: RunAction, patch: Record<string, unknown>) => void; onReject: (action: RunAction) => void; onRetry: (action: RunAction) => void; onAttachDescriptors: (action: RunAction, descriptors: StagedAttachmentDescriptor[]) => Promise<void> | void;
}): JSX.Element {
  const [acknowledgements, setAcknowledgements] = useState<Set<string>>(new Set());
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const requiredAcknowledgements = action.required_acknowledgements ?? [];
  const editableFields = action.editable_fields ?? [];
  const patch = Object.fromEntries(Object.entries(editValues).filter(([, value]) => value.trim()).map(([key, value]) => [key, value.trim()]));
  const missingAcknowledgement = requiredAcknowledgements.some((item) => !acknowledgements.has(item));
  const duplicate = taskDuplicateDecision(action.risk);
  const conflict = calendarConflictDecision(action.risk);
  const feasibility = feasibilityDecision(action.risk);
  const argumentSummary = approvalArgumentSummary(action);
  return (
    <article className="approval-conversation" aria-label={`${actionLabel(action.tool_name)} 승인 요청`} data-tool-name={action.tool_name}>
      <p className="approval-question">{actionLabel(action.tool_name)} 작업을 진행할까요?</p>
      {duplicate === "SIMILAR_CANDIDATE" ? <p className="status-warn">비슷한 기존 작업이 있습니다.</p> : null}
      {duplicate === "CLEAR_DUPLICATE" ? <p className="status-warn">동일한 작업이 이미 있습니다.</p> : null}
      {conflict === "WARNING" ? <p className="status-warn">겹칠 가능성이 있거나 업무 시간 밖의 일정입니다.</p> : null}
      {conflict === "HARD_CONFLICT" ? <p className="status-warn">해당 시간에 기존 일정이 있습니다.</p> : null}
      {feasibility === "RISK" ? <p className="status-warn">현재 일정 기준으로 가능한 시간이 제한적입니다.</p> : null}
      {feasibility === "INFEASIBLE" ? <p className="status-warn">현재 업무 시간과 일정 기준으로 마감 전에 필요한 연속 시간을 확보할 수 없습니다.</p> : null}
      {hasOtherRisk(action.risk) ? <p className="status-warn">서버 검증에서 확인된 위험 정보가 있습니다. 승인 전에 확인해 주세요.</p> : null}
      <details open><summary>무엇을 실행하나요?</summary><dl className="metadata-list"><div><dt>작업</dt><dd>{actionLabel(action.tool_name)}</dd></div><div><dt>실행 방식</dt><dd>{effectLabel(action.effect_type)}</dd></div>{argumentSummary.map((item) => <div key={item.field}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}<div><dt>결과 확인</dt><dd>{verificationLabel(action.verification_policy)}</dd></div></dl></details>
      {approval ? <div className="muted">{approvalStatusLabel(approval.status)} · {formatTime(approval.expires_at_ms)}까지 유효합니다.</div> : null}
      {requiredAcknowledgements.map((item) => (
        <label key={item}><input type="checkbox" checked={acknowledgements.has(item)} onChange={(event) => setAcknowledgements((current) => { const next = new Set(current); if (event.target.checked) next.add(item); else next.delete(item); return next; })} /> {item === "TASK_DUPLICATE" ? "중복 가능성을 확인했습니다." : "일정 충돌 가능성을 확인했습니다."}</label>
      ))}
      {action.next_allowed_commands.includes("MODIFY_ACTION") && editableFields.some((field) => field !== "attachments") ? (
        <fieldset><legend>바꾸고 싶은 내용</legend>{editableFields.filter((field) => field !== "attachments").map((field) => <label key={field}>{argumentLabel(field)}<input value={editValues[field] ?? ""} placeholder={argumentValue(action, field)} onChange={(event) => setEditValues((current) => ({ ...current, [field]: event.target.value }))} /></label>)}<button className="button-secondary" type="button" disabled={busy !== null || Object.keys(patch).length === 0} onClick={() => onModify(action, patch)}>이 내용으로 바꿀게요</button></fieldset>
      ) : null}
      {action.attachment_allowed && action.next_allowed_commands.includes("MODIFY_ACTION") ? <AttachmentPicker disabled={busy !== null} onStaged={(descriptors) => onAttachDescriptors(action, descriptors)} /> : null}
      <div className="button-row">
        {action.next_allowed_commands.includes("APPROVE_ACTION") ? <button className="button-primary" type="button" disabled={busy !== null || missingAcknowledgement} onClick={() => onApprove(action, acknowledgements)}>{approvalLabel(duplicate, conflict)}</button> : null}
        {action.next_allowed_commands.includes("REJECT_ACTION") ? <button className="button-secondary" type="button" disabled={busy !== null} onClick={() => onReject(action)}>이번에는 실행하지 않을게요</button> : null}
        {canRetry ? <button className="button-secondary" type="button" disabled={busy !== null} onClick={() => onRetry(action)}>다시 준비해 주세요</button> : null}
      </div>
      {action.status === "UNKNOWN_RESULT" ? <p className="status-warn">실제 결과를 확인하는 중입니다. 새 쓰기 실행은 잠시 막혀 있습니다.</p> : null}
    </article>
  );
}

function approvalLabel(duplicate: ReturnType<typeof taskDuplicateDecision>, conflict: ReturnType<typeof calendarConflictDecision>): string {
  if (conflict === "HARD_CONFLICT") return "충돌을 알고도 실행해 주세요";
  if (duplicate === "CLEAR_DUPLICATE") return "그래도 새로 만들어 주세요";
  if (conflict === "WARNING" || duplicate === "SIMILAR_CANDIDATE") return "위험을 확인하고 실행해 주세요";
  return "네, 실행해 주세요";
}

function actionLabel(toolName: string): string {
  if (toolName.startsWith("gmail_")) return toolName.includes("send") ? "메일 보내기" : toolName.includes("draft") ? "메일 초안 만들기" : "메일 작업";
  if (toolName.startsWith("tasks_")) return toolName.includes("create") ? "태스크 만들기" : "태스크 변경";
  if (toolName.startsWith("calendar_")) return toolName.includes("create") ? "일정 만들기" : "일정 변경";
  return "요청한 작업";
}

function effectLabel(effectType: string): string {
  return ({ CREATE: "새로 만들기", UPDATE: "내용 변경", DELETE: "삭제", SEND: "보내기" } as Record<string, string>)[effectType] ?? "요청대로 처리";
}

function verificationLabel(policy: string): string {
  return policy === "GET_COMPARE" ? "실행 후 Google에서 다시 확인" : policy === "GET_ABSENT" ? "실행 후 삭제 여부 확인" : "실행 결과 확인";
}

function approvalStatusLabel(status: string): string {
  return ({ ACTIVE: "승인을 기다리고 있습니다.", APPROVED: "승인이 완료됐습니다.", REJECTED: "실행하지 않기로 했습니다.", EXPIRED: "승인 시간이 지났습니다." } as Record<string, string>)[status] ?? "승인 상태를 확인하고 있습니다.";
}

const ARGUMENT_LABELS: Record<string, string> = {
  to: "받는 사람",
  cc: "참조",
  bcc: "숨은 참조",
  subject: "제목",
  body: "본문",
  calendar_id: "캘린더",
  task_list_id: "태스크 목록",
  tasklist_id: "태스크 목록",
  title: "제목",
  start: "시작",
  end: "종료",
  timezone: "시간대",
  due: "마감",
  notes: "메모",
  description: "설명",
  attendees: "참석자",
};

function approvalArgumentSummary(action: RunAction): Array<{ field: string; label: string; value: string }> {
  const preferredFields = action.tool_name.startsWith("gmail_")
    ? ["to", "cc", "bcc", "subject", "body"]
    : action.tool_name.startsWith("tasks_")
      ? ["task_list_id", "title", "due", "notes"]
      : action.tool_name.startsWith("calendar_")
        ? ["calendar_id", "title", "start", "end", "timezone", "description", "attendees"]
        : action.editable_fields;
  return preferredFields.flatMap((field) => {
    const value = argumentValue(action, field);
    return value ? [{ field, label: argumentLabel(field), value }] : [];
  });
}

function argumentValue(action: RunAction, field: string): string {
  const payload = action.arguments.payload;
  const payloadFields = payload && typeof payload === "object" && !Array.isArray(payload)
    ? payload as Record<string, unknown>
    : {};
  const nested = field === "due"
    ? payloadFields.due ?? payloadFields.scheduled_date
    : payloadFields[field];
  const value = nested ?? action.arguments[field];
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (value === null || value === undefined) return "";
  if (field === "task_list_id" && value === "@default") return "내 할 일 목록";
  if (field === "calendar_id" && value === "primary") return "기본 캘린더";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function argumentLabel(field: string): string {
  return ARGUMENT_LABELS[field] ?? field;
}
