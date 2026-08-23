import { Fragment, useEffect, useRef, type Dispatch, type ReactNode, type SetStateAction } from "react";
import type { ConversationMessage, RunAction, RunContext, RunSnapshot } from "../../api/contract";
import { DateSeparator, UserMessageBubble } from "./MessageBubble";
import {
  calendarConflictDecision,
  feasibilityDecision,
  hasOtherRisk,
  taskDuplicateDecision,
} from "./riskPresentation";
import type { PendingConfirmation } from "./useConversation";

export type ConversationViewModel = {
  controller: {
    selectedConversationId: string | null;
    historyMessages: ConversationMessage[];
    runSnapshot: RunSnapshot | null;
    runContext: RunContext | null;
    pendingConfirmation: PendingConfirmation | null;
    confirmationText: string;
    setConfirmationText: Dispatch<SetStateAction<string>>;
    composerText: string;
    composerError: string | null;
    setComposerText: Dispatch<SetStateAction<string>>;
    setComposerError: Dispatch<SetStateAction<string | null>>;
    busyCommand: string | null;
    handleStartRun: (quickPrompt?: string) => Promise<void>;
    handleApprove: (action: RunAction, duplicateAcknowledged?: boolean, calendarConflictAcknowledged?: boolean) => Promise<void>;
    handleSimpleAction: (kind: "modify" | "reject" | "retry", action: RunAction, argumentsPatch?: Record<string, unknown>) => Promise<void>;
    handleAttachFiles: (action: RunAction, files: FileList) => Promise<void>;
    handleCancelRun: () => Promise<void>;
    handleResumeRun: () => Promise<void>;
    handleConfirmation: () => Promise<void>;
    handleResolveRecovery: (action: RunAction, resolutionKind: "ACCEPT_PARTIAL" | "CREATE_CORRECTIVE_PLAN") => Promise<void>;
  };
  resourceContext: { selectedResourceIds: string[]; selectedResourceLabels: string[]; composerPrompt: string };
  formatTime: (value: number) => string;
};

export type ConversationViewProps = { children: ReactNode; viewModel: ConversationViewModel };

export function ConversationView({ children, viewModel }: ConversationViewProps): JSX.Element {
  const { controller: { selectedConversationId, historyMessages, runSnapshot, runContext, pendingConfirmation, confirmationText, setConfirmationText, composerText, composerError, setComposerText, setComposerError, busyCommand, handleStartRun, handleApprove, handleSimpleAction, handleAttachFiles, handleCancelRun, handleResumeRun, handleConfirmation, handleResolveRecovery }, resourceContext: { selectedResourceIds, selectedResourceLabels, composerPrompt }, formatTime } = viewModel;
  const showRunHeader = runSnapshot !== null;
  const isFailedRun = runSnapshot?.status === "FAILED";
  // The stored history already owns every persisted turn. The current run only
  // contributes the request text that is not persisted into history yet.
  const showTransientRequest = Boolean(runContext?.request_text)
    && !historyMessages.some((message) => message.role === "USER" && message.run_id === runContext?.run_id);

  const composerTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    const node = composerTextareaRef.current;
    if (!node) return;
    // CSS max-height clamps the rendered height, so this only needs to grow
    // to fit content -- it never needs to know the cap itself.
    node.style.height = "auto";
    node.style.height = `${node.scrollHeight}px`;
  }, [composerText]);

  const timelineRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const node = timelineRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [selectedConversationId, historyMessages, showTransientRequest]);

  const messagesWithSeparators = groupMessagesByDate(historyMessages);

  return (
    <>          {showRunHeader ? (
            <div className={`panel-header run-header${isFailedRun ? " run-header--failed" : ""}`}>
              <div>
                <strong>{runHeaderTitle(runSnapshot.status, Boolean(selectedConversationId))}</strong>
                <div className="muted">{userRunStatus(runSnapshot.status)}</div>
                {runSnapshot.result_kind === "PARTIAL" ? (
                  <div className="status-warn">일부 작업은 완료되었고 나머지는 취소되었습니다.</div>
                ) : null}
              </div>
              <div className="button-row">
                {runSnapshot.next_allowed_commands.includes("REQUEST_CANCEL") ? (
                  <button className="button-danger" type="button" onClick={() => void handleCancelRun()}>
                    취소
                  </button>
                ) : null}
                {runSnapshot.next_allowed_commands.includes("RESUME") ? (
                  <button className="button-secondary" type="button" onClick={() => void handleResumeRun()}>
                    재개
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}
      <div className="panel-body">
        <div className="central-scroll-area" ref={timelineRef}>
        {children}
        <section className="agent-workspace" aria-label="에이전트 대화">
              <section className="card-list">
              {messagesWithSeparators.map(({ message, separatorLabel }) => (
                <Fragment key={message.id}>
                  {separatorLabel ? <DateSeparator label={separatorLabel} /> : null}
                  {message.role === "USER" ? (
                    <UserMessageBubble content={message.content} createdAtMs={message.created_at_ms} />
                  ) : (
                    <article className="info-card">
                      <strong>{historyMessageLabel(message.role)}</strong>
                      <p>{message.content}</p>
                    </article>
                  )}
                </Fragment>
              ))}

              {showTransientRequest ? (
                <UserMessageBubble content={runContext!.request_text} />
              ) : null}

              {runSnapshot?.status === "WAITING_CONFIRMATION" ? (
                <article className="info-card">
                  <strong>추가 확인</strong>
                  <p>
                    {pendingConfirmation?.question ?? "확인 요청 정보를 동기화하고 있습니다."}
                  </p>
                  <textarea
                    aria-label="확인 응답"
                    className="composer"
                    disabled={!pendingConfirmation}
                    value={confirmationText}
                    onChange={(event) => setConfirmationText(event.target.value)}
                  />
                  <button
                    className="button-primary"
                    type="button"
                    disabled={
                      !pendingConfirmation ||
                      !confirmationText.trim() ||
                      busyCommand === "confirm-run"
                    }
                    onClick={() => void handleConfirmation()}
                  >
                    응답 보내기
                  </button>
                </article>
              ) : null}

              {runSnapshot?.active_plan ? (
                <article className="info-card">
                  <strong>Action Plan</strong>
                  <div className="muted">{runSnapshot.active_plan.summary_text ?? "요약이 아직 없습니다."}</div>
                  <div className="muted">Action {runSnapshot.execution_status.action_count}건</div>
                </article>
              ) : null}

              {runSnapshot?.actions.map((action) => {
                const approval = runSnapshot.approvals.find((item) => item.action_id === action.action_id);
                const feasibility = feasibilityDecision(action.risk);
                const waitingApproval =
                  action.approval_required &&
                  feasibility !== "INFEASIBLE" &&
                  ["PROPOSED", "MODIFIED"].includes(action.status);
                const duplicateDecision = taskDuplicateDecision(action.risk);
                const duplicateNeedsAcknowledgement =
                  duplicateDecision === "SIMILAR_CANDIDATE" ||
                  duplicateDecision === "CLEAR_DUPLICATE";
                const conflictDecision = calendarConflictDecision(action.risk);
                const conflictNeedsAcknowledgement =
                  conflictDecision === "WARNING" ||
                  conflictDecision === "HARD_CONFLICT";
                return (
                  <article key={action.action_id} className="info-card">
                    <div className="inline-row" style={{ justifyContent: "space-between" }}>
                      <strong>{action.tool_name}</strong>
                      <span className="pill">{action.status}</span>
                    </div>
                    <div className="muted">
                      {action.effect_type} / {action.verification_policy}
                    </div>
                    {duplicateDecision === "SIMILAR_CANDIDATE" ? (
                      <p className="status-warn">비슷한 기존 작업이 있습니다.</p>
                    ) : null}
                    {duplicateDecision === "CLEAR_DUPLICATE" ? (
                      <p className="status-warn">
                        동일한 작업이 이미 있습니다. 기존 작업을 확인한 뒤 계속해 주세요.
                      </p>
                    ) : null}
                    {conflictDecision === "WARNING" ? (
                      <p className="status-warn">
                        겹칠 가능성이 있거나 업무 시간 밖의 일정입니다.
                      </p>
                    ) : null}
                    {conflictDecision === "HARD_CONFLICT" ? (
                      <p className="status-warn">해당 시간에 기존 일정이 있습니다.</p>
                    ) : null}
                    {feasibility === "RISK" ? (
                      <p className="status-warn">
                        현재 일정 기준으로 가능한 시간이 제한적입니다.
                      </p>
                    ) : null}
                    {feasibility === "INFEASIBLE" ? (
                      <p className="status-warn">
                        현재 업무 시간과 일정 기준으로 마감 전에 필요한 연속 시간을 확보할 수
                        없습니다.
                      </p>
                    ) : null}
                    {hasOtherRisk(action.risk) ? (
                      <p className="status-warn">
                        서버 검증에서 확인된 위험 정보가 있습니다. 승인 전에 확인해 주세요.
                      </p>
                    ) : null}
                    <details>
                      <summary>승인 상세</summary>
                      <dl className="metadata-list">
                        <div><dt>Action</dt><dd>{action.tool_name}</dd></div>
                        <div><dt>검증</dt><dd>{action.verification_policy}</dd></div>
                      </dl>
                    </details>
                    {approval ? (
                      <div className="muted">
                        승인 상태 {approval.status} / 만료 {formatTime(approval.expires_at_ms)}
                      </div>
                    ) : null}
                    {action.tool_name === "gmail_create_draft" || action.tool_name === "gmail_update_draft" ? (
                      <label className="button-secondary">
                        첨부파일 선택
                        <input
                          type="file"
                          multiple
                          hidden
                          disabled={busyCommand === `modify-${action.action_id}`}
                          onChange={(event) => {
                            if (event.currentTarget.files) void handleAttachFiles(action, event.currentTarget.files);
                            event.currentTarget.value = "";
                          }}
                        />
                      </label>
                    ) : null}
                    {waitingApproval ? (
                      <div className="button-row">
                        <button
                          className="button-primary"
                          type="button"
                          disabled={busyCommand === `approve-${action.action_id}`}
                          onClick={() =>
                            void handleApprove(
                              action,
                              duplicateNeedsAcknowledgement,
                              conflictNeedsAcknowledgement,
                            )
                          }
                        >
                          {conflictDecision === "HARD_CONFLICT"
                            ? "충돌을 알고도 진행"
                            : conflictDecision === "WARNING"
                              ? "확인하고 승인"
                              : duplicateDecision === "CLEAR_DUPLICATE"
                            ? "그래도 새로 만들기"
                            : duplicateDecision === "SIMILAR_CANDIDATE"
                              ? "확인하고 승인"
                              : "승인"}
                        </button>
                        <button
                          className="button-secondary"
                          type="button"
                          disabled={busyCommand === `modify-${action.action_id}`}
                          onClick={() => {
                            const field = action.tool_name.startsWith("gmail_") ? "subject" : "title";
                            const value = window.prompt(field === "subject" ? "새 메일 제목" : "새 제목");
                            if (value?.trim()) void handleSimpleAction("modify", action, { [field]: value.trim() });
                          }}
                        >
                          수정
                        </button>
                        <button
                          className="button-danger"
                          type="button"
                          disabled={busyCommand === `reject-${action.action_id}`}
                          onClick={() => void handleSimpleAction("reject", action)}
                        >
                          건너뛰기
                        </button>
                      </div>
                    ) : null}
                    {action.status === "APPROVED" ? (
                      <div className="button-row">
                        <button
                          className="button-secondary"
                          type="button"
                          disabled={busyCommand === `modify-${action.action_id}`}
                          onClick={() => {
                            const field = action.tool_name.startsWith("gmail_") ? "subject" : "title";
                            const value = window.prompt(field === "subject" ? "새 메일 제목" : "새 제목");
                            if (value?.trim()) void handleSimpleAction("modify", action, { [field]: value.trim() });
                          }}
                        >
                          수정
                        </button>
                        <button
                          className="button-danger"
                          type="button"
                          disabled={busyCommand === `reject-${action.action_id}`}
                          onClick={() => void handleSimpleAction("reject", action)}
                        >
                          거절
                        </button>
                      </div>
                    ) : null}
                    {action.status === "FAILED" ? (
                      <button className="button-secondary" type="button" onClick={() => void handleSimpleAction("retry", action)}>
                        다시 준비
                      </button>
                    ) : null}
                    {action.status === "UNKNOWN_RESULT" ? (
                      <p className="status-warn">실제 결과를 확인하는 중입니다. 새 쓰기 실행은 잠시 막혀 있습니다.</p>
                    ) : null}
                    {action.status === "MISMATCH" ? (
                      <div>
                        <p className="status-warn">
                          실행 결과가 승인 내용과 다릅니다. 자동 수정이나 롤백은 수행하지 않습니다.
                        </p>
                        <div className="button-row">
                          <button
                            className="button-secondary"
                            type="button"
                            onClick={() => void handleResolveRecovery(action, "ACCEPT_PARTIAL")}
                          >
                            현재 결과 수용
                          </button>
                          <button
                            className="button-primary"
                            type="button"
                            onClick={() =>
                              void handleResolveRecovery(action, "CREATE_CORRECTIVE_PLAN")
                            }
                          >
                            새 계획 만들기
                          </button>
                        </div>
                      </div>
                    ) : null}
                  </article>
                );
              })}

              {runSnapshot ? (
                <article className="info-card">
                  <strong>검증 결과</strong>
                  <div className="muted">Verified {runSnapshot.verification_summary.verified_count}</div>
                  <div className="muted">Mismatch {runSnapshot.verification_summary.mismatch_count}</div>
                </article>
              ) : null}

              {runSnapshot?.recovery_summary.unknown_result_action_count ? (
                <article className="info-card">
                  <strong>Recovery</strong>
                  <p>결과 불명 작업 {runSnapshot.recovery_summary.unknown_result_action_count}건을 확인하고 있습니다.</p>
                </article>
              ) : null}
              </section>
        </section>
        </div>

            <div className="composer-dock">
              <div className="composer-surface">
                {selectedResourceIds.length > 0 ? (
                  <div className="composer-context" aria-live="polite">
                    <strong>요청에 사용할 자료 {selectedResourceIds.length}개</strong>
                    {selectedResourceLabels.length > 0 ? (
                      <span>{selectedResourceLabels.join(" · ")}</span>
                    ) : null}
                  </div>
                ) : null}
                <div className="composer-input-row">
                  <textarea
                    ref={composerTextareaRef}
                    className="composer composer--main"
                    aria-label={composerPrompt}
                    placeholder={composerPrompt}
                    rows={1}
                    value={composerText}
                    onChange={(event) => {
                      setComposerText(event.target.value);
                      setComposerError(null);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        void handleStartRun();
                      }
                    }}
                  />
                  <button className="icon-button composer-send" type="button" aria-label="보내기" title="보내기" disabled={busyCommand === "start-run"} onClick={() => void handleStartRun()}>
                    <svg className="composer-send-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                      <path d="M4 4v16l16-8z" />
                    </svg>
                  </button>
                </div>
              </div>
              {composerError ? <p className="status-bad" role="alert">{composerError}</p> : null}
            </div>
      </div>
    </>
  );
}
type MessageWithSeparator = { message: ConversationMessage; separatorLabel: string | null };

function groupMessagesByDate(messages: ConversationMessage[]): MessageWithSeparator[] {
  let lastDateKey: string | null = null;
  return messages.map((message) => {
    const dateKey = localDateKey(message.created_at_ms);
    const separatorLabel = dateKey === lastDateKey ? null : dateSeparatorLabel(message.created_at_ms);
    lastDateKey = dateKey;
    return { message, separatorLabel };
  });
}

function localDateKey(value: number): string {
  const date = new Date(value);
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

function dateSeparatorLabel(value: number, now = new Date()): string {
  const date = new Date(value);
  const isSameDay = (a: Date, b: Date) => (
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
  );
  if (isSameDay(date, now)) return "오늘";
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (isSameDay(date, yesterday)) return "어제";
  const sameYear = date.getFullYear() === now.getFullYear();
  return date.toLocaleDateString("ko-KR", sameYear
    ? { month: "long", day: "numeric" }
    : { year: "numeric", month: "long", day: "numeric" });
}

function historyMessageLabel(role: ConversationMessage["role"]): string {
  switch (role) {
    case "USER":
      return "사용자 요청";
    case "ASSISTANT":
      return "에이전트 응답";
    default:
      return "시스템 메시지";
  }
}

function runHeaderTitle(status: string | undefined, hasConversation: boolean): string {
  if (status === "FAILED") {
    return "실행 실패";
  }
  return hasConversation ? "대화 진행" : "새 요청";
}

function userRunStatus(status: string | undefined): string {
  switch (status) {
    case "WAITING_APPROVAL":
      return "승인이 필요합니다.";
    case "WAITING_CONFIRMATION":
      return "추가 정보를 확인하고 있습니다.";
    case "PLANNING":
      return "요청을 검토하고 있습니다.";
    case "RETRIEVING":
      return "관련 자료를 확인하고 있습니다.";
    case "VERIFYING":
      return "작업 결과를 확인하고 있습니다.";
    case "COMPLETED":
    case "SUCCEEDED":
      return "작업이 완료되었습니다.";
    case "FAILED":
      return "작업을 완료하지 못했습니다.";
    case "RECOVERY_REQUIRED":
      return "실제 결과를 확인해야 합니다.";
    default:
      return "작업을 처리하고 있습니다.";
  }
}
