import { useCallback, useEffect, useRef, useState } from "react";
import {
  approveAction,
  cancelRun,
  confirmRun,
  createConversation,
  getConversationHistory,
  getLatestConversationRun,
  getRunContext,
  getRunSnapshot,
  listConversations,
  modifyAction,
  stageAttachment,
  prepareRetry,
  rejectAction,
  resolveRecovery,
  resumeRun,
  startRun,
} from "../../api";
import type { ConversationHistoryResponse, ConversationItem, ConversationMessage, CurrentGoogleAccountResponse, RunAction, RunContext, RunSnapshot } from "../../api/contract";
import { ApiClientError } from "../../api/client";
import { subscribeRunEvents } from "../../api/sse";

export type PendingConfirmation = {
  interruptId: string;
  question: string;
};

type UseConversationOptions = {
  currentAccount: CurrentGoogleAccountResponse["account"];
  selectedResourceIds: string[];
  onStatusLine: (message: string) => void;
};

export function useConversation({ currentAccount, selectedResourceIds, onStatusLine }: UseConversationOptions) {
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [runSnapshot, setRunSnapshot] = useState<RunSnapshot | null>(null);
  const [runContext, setRunContext] = useState<RunContext | null>(null);
  const [historyMessages, setHistoryMessages] = useState<ConversationMessage[]>([]);
  const [composerText, setComposerText] = useState("");
  const [composerError, setComposerError] = useState<string | null>(null);
  const [busyCommand, setBusyCommand] = useState<string | null>(null);
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null);
  const [confirmationText, setConfirmationText] = useState("");
  const subscriptionRef = useRef<(() => void) | null>(null);
  const subscriptionRunIdRef = useRef<string | null>(null);
  const conversationProjectionRef = useRef({ generation: 0, conversationId: null as string | null });
  const historySyncedRunIdsRef = useRef(new Set<string>());

  useEffect(() => () => subscriptionRef.current?.(), []);

  const refreshConversations = useCallback(async (accountId: string): Promise<void> => {
    const response = await listConversations(accountId);
    setConversations(response.items);
  }, []);

  const beginConversationProjection = useCallback((conversationId: string | null): number => {
    const generation = conversationProjectionRef.current.generation + 1;
    conversationProjectionRef.current = { generation, conversationId };
    subscriptionRef.current?.();
    subscriptionRef.current = null;
    subscriptionRunIdRef.current = null;
    historySyncedRunIdsRef.current = new Set<string>();
    setSelectedConversationId(conversationId);
    setHistoryMessages([]);
    setRunSnapshot(null);
    setRunContext(null);
    setPendingConfirmation(null);
    setConfirmationText("");
    setComposerError(null);
    return generation;
  }, []);

  const isCurrentProjection = useCallback((conversationId: string, generation: number): boolean => (
    conversationProjectionRef.current.generation === generation
    && conversationProjectionRef.current.conversationId === conversationId
  ), []);

  // Stored Domain history only. Runs that already finished need no further sync,
  // so their transient projection never re-fetches the same rows.
  const applyConversationHistory = useCallback((
    history: ConversationHistoryResponse,
    conversationId: string,
    generation: number,
  ): boolean => {
    if (!isCurrentProjection(conversationId, generation)) return false;
    setHistoryMessages(history.messages);
    for (const run of history.runs) {
      if (run.finished_at_ms !== null) historySyncedRunIdsRef.current.add(run.run_id);
    }
    return true;
  }, [isCurrentProjection]);

  const reloadConversationHistory = useCallback(async (
    conversationId: string,
    generation: number,
  ): Promise<void> => {
    try {
      applyConversationHistory(await getConversationHistory(conversationId), conversationId, generation);
    } catch (error) {
      if (isCurrentProjection(conversationId, generation)) {
        onStatusLine(error instanceof ApiClientError ? error.message : "이전 대화를 복구하지 못했습니다.");
      }
    }
  }, [applyConversationHistory, isCurrentProjection, onStatusLine]);

  const refreshRun = useCallback(async (
    runId: string,
    conversationId = conversationProjectionRef.current.conversationId,
    generation = conversationProjectionRef.current.generation,
  ): Promise<boolean> => {
    const [snapshotResponse, contextResponse] = await Promise.all([getRunSnapshot(runId), getRunContext(runId)]);
    if (conversationId === null || snapshotResponse.snapshot.conversation_id !== conversationId || conversationProjectionRef.current.generation !== generation || conversationProjectionRef.current.conversationId !== conversationId) return false;
    setRunSnapshot(snapshotResponse.snapshot);
    setRunContext(contextResponse.context);
    setPendingConfirmation((current) => snapshotResponse.snapshot.status === "WAITING_CONFIRMATION" ? current : null);
    if (
      snapshotResponse.snapshot.finished_at_ms !== null
      && snapshotResponse.snapshot.finished_at_ms !== undefined
      && !historySyncedRunIdsRef.current.has(runId)
    ) {
      historySyncedRunIdsRef.current.add(runId);
      await reloadConversationHistory(conversationId, generation);
    }
    return true;
  }, [reloadConversationHistory]);

  const selectRun = useCallback(async (runId: string, conversationId = conversationProjectionRef.current.conversationId, generation = conversationProjectionRef.current.generation): Promise<void> => {
    if (conversationId === null) {
      const snapshotResponse = await getRunSnapshot(runId);
      if (conversationProjectionRef.current.generation !== generation) return;
      const resolvedConversationId = snapshotResponse.snapshot.conversation_id;
      const resolvedGeneration = beginConversationProjection(resolvedConversationId);
      await Promise.all([
        reloadConversationHistory(resolvedConversationId, resolvedGeneration),
        selectRun(runId, resolvedConversationId, resolvedGeneration),
      ]);
      return;
    }
    if (!await refreshRun(runId, conversationId, generation)) return;
    if (subscriptionRunIdRef.current === runId && subscriptionRef.current) return;
    subscriptionRef.current?.();
    subscriptionRef.current = subscribeRunEvents(runId, {
      onStateChange: onStatusLine,
      onEvent: (event) => {
        if (event.eventType === "confirmation_required") {
          const interrupt = event.payload.user_interrupt;
          if (interrupt && typeof interrupt === "object") {
            const values = interrupt as Record<string, unknown>;
            if (typeof values.interrupt_id === "string") setPendingConfirmation({ interruptId: values.interrupt_id, question: typeof values.question === "string" ? values.question : "계속하려면 필요한 내용을 확인해 주세요." });
          }
        }
        void refreshRun(runId, conversationId, generation);
      },
    });
    subscriptionRunIdRef.current = runId;
  }, [beginConversationProjection, onStatusLine, refreshRun, reloadConversationHistory]);

  const selectConversation = useCallback(async (conversationId: string): Promise<void> => {
    const generation = beginConversationProjection(conversationId);
    try {
      const [history, latest] = await Promise.all([
        getConversationHistory(conversationId),
        getLatestConversationRun(conversationId),
      ]);
      if (!applyConversationHistory(history, conversationId, generation)) return;
      if (latest.run) await selectRun(latest.run.run_id, conversationId, generation);
    } catch (error) {
      if (conversationProjectionRef.current.generation === generation && conversationProjectionRef.current.conversationId === conversationId) {
        const message = error instanceof ApiClientError ? error.message : "대화 실행 정보를 불러오지 못했습니다.";
        onStatusLine(message);
        setComposerError(message);
      }
    }
  }, [applyConversationHistory, beginConversationProjection, onStatusLine, selectRun]);

  const handleStartRun = useCallback(async (quickPrompt?: string): Promise<void> => {
    if (!currentAccount?.account_id) {
      const message = "현재 연결된 계정 정보를 찾지 못했습니다.";
      onStatusLine(message);
      setComposerError(message);
      return;
    }
    const requestText = (quickPrompt ?? composerText).trim();
    if (!requestText || busyCommand) return;
    setBusyCommand("start-run");
    setComposerError(null);
    try {
      const conversationId = selectedConversationId ?? crypto.randomUUID();
      let projectionGeneration = conversationProjectionRef.current.generation;
      if (!selectedConversationId) {
        await createConversation({ command_id: crypto.randomUUID(), conversation_id: conversationId, account_id: currentAccount.account_id, title: requestText.slice(0, 80) });
        projectionGeneration = beginConversationProjection(conversationId);
      }
      const runId = crypto.randomUUID();
      const response = await startRun({ command_id: crypto.randomUUID(), conversation_id: conversationId, user_message_id: crypto.randomUUID(), run_id: runId, workflow_key: `workflow-${runId}`, request_text: requestText, entry_mode: selectedResourceIds.length > 0 ? "RESOURCE_SELECTED" : "AGENT_SEARCH", selected_resource_ids: selectedResourceIds, requested_mode: "AUTO" });
      await reloadConversationHistory(conversationId, projectionGeneration);
      // The just-started run advances the conversation's server-side
      // updated_at_ms, so the sidebar list (sorted by that field) needs a
      // refetch here regardless of whether this conversation is new.
      await refreshConversations(currentAccount.account_id);
      await selectRun(response.run_id, conversationId, projectionGeneration);
      setComposerText("");
    } catch (error) {
      const message = error instanceof ApiClientError ? error.message : "요청을 시작하지 못했습니다.";
      onStatusLine(message);
      setComposerError(message);
    } finally { setBusyCommand(null); }
  }, [beginConversationProjection, busyCommand, composerText, currentAccount, onStatusLine, refreshConversations, reloadConversationHistory, selectRun, selectedConversationId, selectedResourceIds]);

  const handleApprove = useCallback(async (action: RunAction, duplicateAcknowledged = false, calendarConflictAcknowledged = false): Promise<void> => {
    if (!runSnapshot || !currentAccount?.account_id || busyCommand) return;
    setBusyCommand(`approve-${action.action_id}`);
    try { await approveAction({ action_id: action.action_id, command_id: crypto.randomUUID(), expected_version: action.version, duplicate_acknowledged: duplicateAcknowledged, calendar_conflict_acknowledged: calendarConflictAcknowledged }); await selectRun(runSnapshot.run_id); } finally { setBusyCommand(null); }
  }, [busyCommand, currentAccount, runSnapshot, selectRun]);
  const handleSimpleAction = useCallback(async (kind: "modify" | "reject" | "retry", action: RunAction, argumentsPatch: Record<string, unknown> = {}): Promise<void> => {
    if (!runSnapshot || busyCommand) return;
    setBusyCommand(`${kind}-${action.action_id}`);
    try { const commandId = crypto.randomUUID(); if (kind === "modify") await modifyAction({ action_id: action.action_id, command_id: commandId, expected_version: action.version, arguments_patch: argumentsPatch }); else if (kind === "reject") await rejectAction({ action_id: action.action_id, command_id: commandId, expected_version: action.version }); else await prepareRetry({ action_id: action.action_id, command_id: commandId, expected_action_version: action.version }); await selectRun(runSnapshot.run_id); } finally { setBusyCommand(null); }
  }, [busyCommand, runSnapshot, selectRun]);
  const handleAttachFiles = useCallback(async (action: RunAction, files: FileList): Promise<void> => {
    if (!runSnapshot || busyCommand || files.length === 0) return;
    setBusyCommand(`modify-${action.action_id}`);
    try {
      const descriptors = [];
      for (const file of Array.from(files).slice(0, 10)) {
        const staged = await stageAttachment(file);
        descriptors.push({
          staged_attachment_id: staged.staged_attachment_id,
          filename: staged.filename,
          mime_type: staged.mime_type,
          size_bytes: staged.size_bytes,
          sha256: staged.sha256,
        });
      }
      await modifyAction({ action_id: action.action_id, command_id: crypto.randomUUID(), expected_version: action.version, arguments_patch: { attachments: descriptors } });
      await selectRun(runSnapshot.run_id);
    } catch (error) {
      onStatusLine(error instanceof ApiClientError ? error.message : "첨부파일을 추가하지 못했습니다.");
    } finally {
      setBusyCommand(null);
    }
  }, [busyCommand, onStatusLine, runSnapshot, selectRun]);
  const handleCancelRun = useCallback(async (): Promise<void> => { if (!runSnapshot || busyCommand) return; setBusyCommand("cancel-run"); try { await cancelRun({ run_id: runSnapshot.run_id, command_id: crypto.randomUUID(), expected_run_version: runSnapshot.version }); await selectRun(runSnapshot.run_id); } finally { setBusyCommand(null); } }, [busyCommand, runSnapshot, selectRun]);
  const handleResumeRun = useCallback(async (): Promise<void> => { if (!runSnapshot || busyCommand) return; const resumeKind = { REAUTH_REQUIRED: "REAUTH_COMPLETED", BLOCKED: "SAFE_CHECKPOINT_RESUME", RECOVERY_REQUIRED: "RECOVERY_RECHECK" }[runSnapshot.status] as "REAUTH_COMPLETED" | "SAFE_CHECKPOINT_RESUME" | "RECOVERY_RECHECK" | undefined; if (!resumeKind) { onStatusLine("현재 상태는 전용 확인 또는 승인 경로를 사용해야 합니다."); return; } setBusyCommand("resume-run"); try { await resumeRun({ run_id: runSnapshot.run_id, command_id: crypto.randomUUID(), expected_version: runSnapshot.version, resume_kind: resumeKind }); await selectRun(runSnapshot.run_id); } finally { setBusyCommand(null); } }, [busyCommand, onStatusLine, runSnapshot, selectRun]);
  const handleConfirmation = useCallback(async (): Promise<void> => { if (!runSnapshot || !pendingConfirmation || !confirmationText.trim() || busyCommand) return; setBusyCommand("confirm-run"); try { await confirmRun({ run_id: runSnapshot.run_id, command_id: crypto.randomUUID(), expected_version: runSnapshot.version, interrupt_id: pendingConfirmation.interruptId, response_kind: "FREE_TEXT", free_text: confirmationText.trim() }); setConfirmationText(""); await refreshRun(runSnapshot.run_id); } finally { setBusyCommand(null); } }, [busyCommand, confirmationText, pendingConfirmation, refreshRun, runSnapshot]);
  const handleResolveRecovery = useCallback(async (action: RunAction, resolutionKind: "ACCEPT_PARTIAL" | "CREATE_CORRECTIVE_PLAN"): Promise<void> => { if (!runSnapshot || busyCommand) return; setBusyCommand(`recovery-${resolutionKind}`); try { await resolveRecovery({ run_id: runSnapshot.run_id, command_id: crypto.randomUUID(), expected_version: runSnapshot.version, action_id: action.action_id, resolution_kind: resolutionKind }); await refreshRun(runSnapshot.run_id); } finally { setBusyCommand(null); } }, [busyCommand, refreshRun, runSnapshot]);

  return { conversations, selectedConversationId, historyMessages, runSnapshot, runContext, composerText, composerError, busyCommand, pendingConfirmation, confirmationText, setComposerText, setComposerError, setConfirmationText, refreshConversations, beginConversationProjection, selectConversation, selectRun, refreshRun, handleStartRun, handleApprove, handleSimpleAction, handleAttachFiles, handleCancelRun, handleResumeRun, handleConfirmation, handleResolveRecovery };
}
