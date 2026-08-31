import { useCallback, useEffect, useRef, useState } from "react";
import type { RunContext, RunSnapshot } from "../../api/contract";
import { getRunContext, getRunSnapshot } from "./api/get_run_snapshot";
import { cancelRun, confirmRun, resumeRun } from "./api/run_commands";
import { subscribeRunEvents } from "./api/subscribe_run_events";

export type PendingConfirmation = {
  interruptId: string;
  question: string;
  options: string[];
  responseMode: "OPTION" | "FREE_TEXT";
};

type ProjectionIdentity = { conversationId: string | null; generation: number };

type UseRunProjectionOptions = {
  busyCommand: string | null;
  setBusyCommand: (value: string | null) => void;
  commandIdFor: (operation: string) => string;
  completeCommand: (operation: string) => void;
  beginConversationProjection: (conversationId: string) => number;
  getConversationProjection: () => ProjectionIdentity;
  isCurrentProjection: (conversationId: string, generation: number) => boolean;
  reloadConversationHistory: (conversationId: string, generation: number) => Promise<void>;
  selectConversationHistory: (conversationId: string, selectRun: (runId: string, conversationId?: string, generation?: number) => Promise<void>) => Promise<void>;
  isRunHistorySynced: (runId: string) => boolean;
  markRunHistorySynced: (runId: string) => void;
  onStatusLine: (message: string) => void;
};

export function useRunProjection({ busyCommand, setBusyCommand, commandIdFor, completeCommand, beginConversationProjection, getConversationProjection, isCurrentProjection, reloadConversationHistory, selectConversationHistory, isRunHistorySynced, markRunHistorySynced, onStatusLine }: UseRunProjectionOptions) {
  const [runSnapshot, setRunSnapshot] = useState<RunSnapshot | null>(null);
  const [runContext, setRunContext] = useState<RunContext | null>(null);
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null);
  const [confirmationText, setConfirmationText] = useState("");
  const subscriptionRef = useRef<(() => void) | null>(null);
  const subscriptionRunIdRef = useRef<string | null>(null);

  const resetRunProjection = useCallback((): void => {
    subscriptionRef.current?.();
    subscriptionRef.current = null;
    subscriptionRunIdRef.current = null;
    setRunSnapshot(null);
    setRunContext(null);
    setPendingConfirmation(null);
    setConfirmationText("");
  }, []);

  useEffect(() => () => subscriptionRef.current?.(), []);

  const refreshRun = useCallback(async (runId: string, conversationId = getConversationProjection().conversationId, generation = getConversationProjection().generation): Promise<boolean> => {
    const [snapshot, contextResponse] = await Promise.all([getRunSnapshot(runId), getRunContext(runId)]);
    if (conversationId === null || snapshot.run.conversation_id !== conversationId || !isCurrentProjection(conversationId, generation)) return false;
    setRunSnapshot(snapshot);
    setRunContext(contextResponse.context);
    const pending = snapshot.pending_interrupt;
    setPendingConfirmation(pending ? { interruptId: pending.interrupt_id, question: pending.question, options: pending.options, responseMode: pending.response_mode } : null);
    if (snapshot.run.finished_at_ms !== null && !isRunHistorySynced(runId)) {
      markRunHistorySynced(runId);
      await reloadConversationHistory(conversationId, generation);
    }
    return true;
  }, [getConversationProjection, isCurrentProjection, isRunHistorySynced, markRunHistorySynced, reloadConversationHistory]);

  const selectRun = useCallback(async (runId: string, conversationId = getConversationProjection().conversationId, generation = getConversationProjection().generation): Promise<void> => {
    if (conversationId === null) {
      const snapshot = await getRunSnapshot(runId);
      if (getConversationProjection().generation !== generation) return;
      const resolvedConversationId = snapshot.run.conversation_id;
      const resolvedGeneration = beginConversationProjection(resolvedConversationId);
      await Promise.all([reloadConversationHistory(resolvedConversationId, resolvedGeneration), selectRun(runId, resolvedConversationId, resolvedGeneration)]);
      return;
    }
    if (!await refreshRun(runId, conversationId, generation)) return;
    if (subscriptionRunIdRef.current === runId && subscriptionRef.current) return;
    subscriptionRef.current?.();
    subscriptionRef.current = subscribeRunEvents(runId, {
      onStateChange: onStatusLine,
      onEvent: () => { void refreshRun(runId, conversationId, generation); },
      onSnapshotRequired: () => {
        subscriptionRef.current = null;
        subscriptionRunIdRef.current = null;
        void refreshRun(runId, conversationId, generation).then((current) => { if (current) void selectRun(runId, conversationId, generation); });
      },
    });
    subscriptionRunIdRef.current = runId;
  }, [beginConversationProjection, getConversationProjection, onStatusLine, refreshRun, reloadConversationHistory]);

  const selectConversation = useCallback(async (conversationId: string): Promise<void> => {
    await selectConversationHistory(conversationId, selectRun);
  }, [selectConversationHistory, selectRun]);

  const handleCancelRun = useCallback(async (): Promise<void> => {
    if (!runSnapshot || busyCommand) return;
    const operation = "cancel-run";
    setBusyCommand(operation);
    try {
      await cancelRun({ run_id: runSnapshot.run.run_id, command_id: commandIdFor(operation), expected_version: runSnapshot.run.version });
      completeCommand(operation);
      await selectRun(runSnapshot.run.run_id);
    } catch (error) {
      await refreshRun(runSnapshot.run.run_id);
      throw error;
    } finally { setBusyCommand(null); }
  }, [busyCommand, commandIdFor, completeCommand, refreshRun, runSnapshot, selectRun, setBusyCommand]);

  const handleResumeRun = useCallback(async (resumeKind: "SAFE_CHECKPOINT_RESUME"): Promise<void> => {
    if (!runSnapshot || busyCommand) return;
    if (!runSnapshot.error?.actions.some((action) => action.kind === "RESUME_SAFE_CHECKPOINT" && action.resume_kind === resumeKind)) return;
    const operation = "resume-run";
    setBusyCommand(operation);
    try {
      await resumeRun({ run_id: runSnapshot.run.run_id, command_id: commandIdFor(operation), expected_version: runSnapshot.run.version, resume_kind: resumeKind });
      completeCommand(operation);
      await selectRun(runSnapshot.run.run_id);
    } catch (error) {
      await refreshRun(runSnapshot.run.run_id);
      throw error;
    } finally { setBusyCommand(null); }
  }, [busyCommand, commandIdFor, completeCommand, refreshRun, runSnapshot, selectRun, setBusyCommand]);

  const handleConfirmation = useCallback(async (selectedOption?: string): Promise<void> => {
    if (!runSnapshot || !pendingConfirmation || busyCommand) return;
    const isOption = pendingConfirmation.responseMode === "OPTION";
    const freeText = confirmationText.trim();
    if ((isOption && !selectedOption) || (!isOption && !freeText)) return;
    setBusyCommand("confirm-run");
    try {
      await confirmRun({ run_id: runSnapshot.run.run_id, command_id: commandIdFor("confirm-run"), expected_version: runSnapshot.run.version, interrupt_id: pendingConfirmation.interruptId, response_kind: isOption ? "OPTION" : "FREE_TEXT", selected_option: isOption ? selectedOption : null, free_text: isOption ? null : freeText });
      completeCommand("confirm-run");
      setConfirmationText("");
      await refreshRun(runSnapshot.run.run_id);
    } catch (error) {
      await refreshRun(runSnapshot.run.run_id);
      throw error;
    } finally { setBusyCommand(null); }
  }, [busyCommand, commandIdFor, completeCommand, confirmationText, pendingConfirmation, refreshRun, runSnapshot, setBusyCommand]);

  return { runSnapshot, runContext, pendingConfirmation, confirmationText, setConfirmationText, resetRunProjection, refreshRun, selectRun, selectConversation, handleCancelRun, handleResumeRun, handleConfirmation };
}
