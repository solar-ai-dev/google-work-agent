import { Fragment, useEffect, useRef, type Dispatch, type ReactNode, type SetStateAction } from "react";
import type { ConversationMessage, RunAction, RunContext, RunSnapshot } from "../../api/contract";
import type { StagedAttachmentDescriptor } from "../attachment";
import { ActionPlanCard } from "../approval";
import { RecoveryCard } from "../recovery";
import { ConfirmationCard, ContextPreviewCard, ExecutionStatusCard, ExternalLlmDisclosureCard, RequestComposer, RunProgress } from "../run";
import type { RunSseEvent } from "../run/api/run_sse_event";
import { AssistantMessageBubble, DateSeparator, UserMessageBubble } from "./MessageBubble";

type RecoveryKind = NonNullable<RunSnapshot["recovery"]>["allowed_resolution_kinds"][number];

export type ConversationViewModel = {
  controller: {
    selectedConversationId: string | null;
    historyMessages: ConversationMessage[];
    runSnapshot: RunSnapshot | null;
    runContext: RunContext | null;
    latestRunEvent?: RunSseEvent | null;
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
    handleAttachDescriptors: (action: RunAction, descriptors: StagedAttachmentDescriptor[]) => Promise<void>;
    handleCancelRun: () => Promise<void>;
    handleResumeRun: (resumeKind: "SAFE_CHECKPOINT_RESUME") => Promise<void>;
    handleAdjustContext: (kind: "EXCLUDE_EVIDENCE" | "RETRIEVE_MORE", value: string[] | string) => Promise<void>;
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
  const { selectedConversationId, historyMessages, runSnapshot, runContext, latestRunEvent, confirmationText, setConfirmationText, composerText, composerError, setComposerText, setComposerError, busyCommand, handleStartRun, handleApprove, handleSimpleAction, handleAttachDescriptors, handleCancelRun, handleResumeRun, handleAdjustContext, handleConfirmation, handleResolveRecovery } = controller;
  const timelineMessages = mergeConversationMessages(
    historyMessages,
    runSnapshot?.messages ?? [],
  );
  const showTransientRequest = Boolean(runContext?.request_text)
    && !timelineMessages.some((message) => message.role === "USER" && message.run_id === runContext?.run_id);
  const isTerminal = runSnapshot !== null
    && ["COMPLETED", "BLOCKED", "FAILED", "CANCELLED"].includes(runSnapshot.run.status);
  const timelineRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const node = timelineRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [selectedConversationId, timelineMessages, latestRunEvent?.event_id, runSnapshot?.projection_version, showTransientRequest]);
  const retryActionIds = new Set(runSnapshot?.error?.actions.filter((action) => action.kind === "PREPARE_RETRY" && action.action_id).map((action) => action.action_id!) ?? []);

  return (
    <>
      <div className="panel-body">
        <div className="central-scroll-area" ref={timelineRef}>
          {children}
          <section className="agent-workspace" aria-label="에이전트 대화">
            <section className="card-list">
              {groupMessagesByDate(timelineMessages).map(({ message, separatorLabel }) => (
                <Fragment key={message.id}>
                  {separatorLabel ? <DateSeparator label={separatorLabel} /> : null}
                  {message.role === "USER" ? <UserMessageBubble content={message.content} createdAtMs={message.created_at_ms} /> : message.role === "ASSISTANT" ? <AssistantMessageBubble content={message.content} createdAtMs={message.created_at_ms} /> : <article className="info-card"><strong>시스템 메시지</strong><p>{message.content}</p></article>}
                </Fragment>
              ))}
              {showTransientRequest ? <UserMessageBubble content={runContext!.request_text} /> : null}
              {runSnapshot && !isTerminal ? <RunProgress snapshot={runSnapshot} latestEvent={latestRunEvent} busy={busyCommand} onResume={(kind) => void handleResumeRun(kind)} /> : null}
              {!isTerminal && runSnapshot?.pending_interrupt ? <ConfirmationCard interrupt={runSnapshot.pending_interrupt} text={confirmationText} busy={busyCommand === "confirm-run"} onTextChange={setConfirmationText} onSubmit={(option) => void handleConfirmation(option)} /> : null}
              {runSnapshot && !isTerminal ? <div className="action-execution-flow"><ActionPlanCard snapshot={runSnapshot} busy={busyCommand} retryActionIds={retryActionIds} formatTime={formatTime} onApprove={(action, acknowledgements) => void handleApprove(action, acknowledgements)} onModify={(action, patch) => void handleSimpleAction("modify", action, patch)} onReject={(action) => void handleSimpleAction("reject", action)} onRetry={(action) => void handleSimpleAction("retry", action)} onAttachDescriptors={(action, descriptors) => handleAttachDescriptors(action, descriptors)} /><ExecutionStatusCard snapshot={runSnapshot} /></div> : null}
              {runSnapshot && !isTerminal ? <RecoveryCard snapshot={runSnapshot} busy={busyCommand} onResolve={(kind) => void handleResolveRecovery(kind)} onErrorAction={(kind) => kind === "OPEN_DIAGNOSTICS" ? onOpenDiagnostics() : onOpenSettings()} /> : null}
            </section>
          </section>
        </div>
        {runSnapshot?.external_llm_transfer_scope ? <ExternalLlmDisclosureCard scope={runSnapshot.external_llm_transfer_scope} /> : null}
        {runSnapshot?.context_preview ? <ContextPreviewCard preview={runSnapshot.context_preview} busy={busyCommand?.startsWith("adjust-context:") ?? false} onAdjust={handleAdjustContext} /> : null}
        <RequestComposer text={composerText} error={composerError} busy={busyCommand === "start-run"} activeRun={Boolean(runSnapshot && !isTerminal)} cancelAllowed={runSnapshot?.run.next_allowed_commands.includes("REQUEST_CANCEL") ?? false} cancelling={busyCommand === "cancel-run"} prompt={resourceContext.composerPrompt} selectedResourceLabels={resourceContext.selectedResourceLabels} setText={setComposerText} setError={setComposerError} onSubmit={handleStartRun} onCancel={handleCancelRun} />
      </div>
    </>
  );
}

export function mergeConversationMessages(
  historyMessages: ConversationMessage[],
  snapshotMessages: ConversationMessage[],
): ConversationMessage[] {
  const byId = new Map(historyMessages.map((message) => [message.id, message]));
  for (const message of snapshotMessages) byId.set(message.id, message);
  return Array.from(byId.values()).sort(
    (left, right) => left.created_at_ms - right.created_at_ms || left.id.localeCompare(right.id),
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
