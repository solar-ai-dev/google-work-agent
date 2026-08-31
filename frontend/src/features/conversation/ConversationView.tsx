import { Fragment, useEffect, useRef, type Dispatch, type ReactNode, type SetStateAction } from "react";
import type { ConversationMessage, RunAction, RunContext, RunSnapshot } from "../../api/contract";
import { ActionPlanCard } from "../approval/action_plan_card";
import { RecoveryCard } from "../recovery/recovery_card";
import { ConfirmationCard } from "../run/confirmation_card";
import { ExecutionStatusCard } from "../run/execution_status_card";
import { RequestComposer } from "../run/request_composer";
import { RunProgress } from "../run/run_progress";
import { DateSeparator, UserMessageBubble } from "./MessageBubble";

type RecoveryKind = NonNullable<RunSnapshot["recovery"]>["allowed_resolution_kinds"][number];

export type ConversationViewModel = {
  controller: {
    selectedConversationId: string | null;
    historyMessages: ConversationMessage[];
    runSnapshot: RunSnapshot | null;
    runContext: RunContext | null;
    confirmationText: string;
    setConfirmationText: Dispatch<SetStateAction<string>>;
    composerText: string;
    composerError: string | null;
    setComposerText: Dispatch<SetStateAction<string>>;
    setComposerError: Dispatch<SetStateAction<string | null>>;
    busyCommand: string | null;
    handleStartRun: (quickPrompt?: string) => Promise<void>;
    handleApprove: (action: RunAction, acknowledgements?: ReadonlySet<string>) => Promise<void>;
    handleSimpleAction: (kind: "modify" | "reject" | "retry", action: RunAction, argumentsPatch?: Record<string, unknown>) => Promise<void>;
    handleAttachFiles: (action: RunAction, files: FileList) => Promise<void>;
    handleCancelRun: () => Promise<void>;
    handleResumeRun: (resumeKind: "SAFE_CHECKPOINT_RESUME") => Promise<void>;
    handleConfirmation: (selectedOption?: string) => Promise<void>;
    handleResolveRecovery: (resolutionKind: RecoveryKind) => Promise<void>;
  };
  resourceContext: { selectedResourceIds: string[]; selectedResourceLabels: string[]; composerPrompt: string };
  formatTime: (value: number) => string;
  onOpenSettings: () => void;
  onOpenDiagnostics: () => void;
};

export type ConversationViewProps = { children: ReactNode; viewModel: ConversationViewModel };

export function ConversationView({ children, viewModel }: ConversationViewProps): JSX.Element {
  const { controller, resourceContext, formatTime, onOpenSettings, onOpenDiagnostics } = viewModel;
  const { selectedConversationId, historyMessages, runSnapshot, runContext, confirmationText, setConfirmationText, composerText, composerError, setComposerText, setComposerError, busyCommand, handleStartRun, handleApprove, handleSimpleAction, handleAttachFiles, handleCancelRun, handleResumeRun, handleConfirmation, handleResolveRecovery } = controller;
  const showTransientRequest = Boolean(runContext?.request_text)
    && !historyMessages.some((message) => message.role === "USER" && message.run_id === runContext?.run_id);
  const timelineRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const node = timelineRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [selectedConversationId, historyMessages, showTransientRequest]);
  const retryActionIds = new Set(runSnapshot?.error?.actions.filter((action) => action.kind === "PREPARE_RETRY" && action.action_id).map((action) => action.action_id!) ?? []);

  return (
    <>
      {runSnapshot ? <RunProgress snapshot={runSnapshot} busy={busyCommand} onCancel={() => void handleCancelRun()} onResume={(kind) => void handleResumeRun(kind)} /> : null}
      <div className="panel-body">
        <div className="central-scroll-area" ref={timelineRef}>
          {children}
          <section className="agent-workspace" aria-label="에이전트 대화">
            <section className="card-list">
              {groupMessagesByDate(historyMessages).map(({ message, separatorLabel }) => (
                <Fragment key={message.id}>
                  {separatorLabel ? <DateSeparator label={separatorLabel} /> : null}
                  {message.role === "USER" ? <UserMessageBubble content={message.content} createdAtMs={message.created_at_ms} /> : <article className="info-card"><strong>{historyMessageLabel(message.role)}</strong><p>{message.content}</p></article>}
                </Fragment>
              ))}
              {showTransientRequest ? <UserMessageBubble content={runContext!.request_text} /> : null}
              {runSnapshot?.pending_interrupt ? <ConfirmationCard interrupt={runSnapshot.pending_interrupt} text={confirmationText} busy={busyCommand === "confirm-run"} onTextChange={setConfirmationText} onSubmit={(option) => void handleConfirmation(option)} /> : null}
              {runSnapshot ? <ActionPlanCard snapshot={runSnapshot} busy={busyCommand} retryActionIds={retryActionIds} formatTime={formatTime} onApprove={(action, acknowledgements) => void handleApprove(action, acknowledgements)} onModify={(action, patch) => void handleSimpleAction("modify", action, patch)} onReject={(action) => void handleSimpleAction("reject", action)} onRetry={(action) => void handleSimpleAction("retry", action)} onAttachFiles={(action, files) => void handleAttachFiles(action, files)} /> : null}
              {runSnapshot ? <ExecutionStatusCard snapshot={runSnapshot} /> : null}
              {runSnapshot ? <RecoveryCard snapshot={runSnapshot} busy={busyCommand} onResolve={(kind) => void handleResolveRecovery(kind)} onErrorAction={(kind) => kind === "OPEN_DIAGNOSTICS" ? onOpenDiagnostics() : onOpenSettings()} /> : null}
            </section>
          </section>
        </div>
        <RequestComposer text={composerText} error={composerError} busy={busyCommand === "start-run"} prompt={resourceContext.composerPrompt} selectedResourceLabels={resourceContext.selectedResourceLabels} setText={setComposerText} setError={setComposerError} onSubmit={handleStartRun} />
      </div>
    </>
  );
}

type MessageWithSeparator = { message: ConversationMessage; separatorLabel: string | null };

function groupMessagesByDate(messages: ConversationMessage[]): MessageWithSeparator[] {
  let lastDateKey: string | null = null;
  return messages.map((message) => {
    const date = new Date(message.created_at_ms);
    const dateKey = `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
    const separatorLabel = dateKey === lastDateKey ? null : date.toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric" });
    lastDateKey = dateKey;
    return { message, separatorLabel };
  });
}

function historyMessageLabel(role: ConversationMessage["role"]): string {
  return role === "ASSISTANT" ? "에이전트 응답" : role === "USER" ? "사용자 요청" : "시스템 메시지";
}
