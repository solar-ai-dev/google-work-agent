import { useCallback, useEffect, useRef, useState } from "react";
import type { RunContext, RunSnapshot } from "../../api/contract";
import { getRunContext, getRunSnapshot } from "./api/get_run_snapshot";
import { adjustRunContext, cancelRun, confirmRun, resumeRun } from "./api/run_commands";
import { subscribeRunEvents } from "./api/subscribe_run_events";
import type { RunSseEvent } from "./api/run_sse_event";
import { isWorkflowExecutionActive } from "./run_execution_state";

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
  const [latestRunEvent, setLatestRunEvent] = useState<RunSseEvent | null>(null);
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null);
  const [confirmationText, setConfirmationText] = useState("");
  const subscriptionRef = useRef<(() => void) | null>(null);
  const subscriptionRunIdRef = useRef<string | null>(null);
  const snapshotVersionRef = useRef<{ runId: string; generation: number; version: number } | null>(null);

  const resetRunProjection = useCallback((): void => {
    subscriptionRef.current?.();
    subscriptionRef.current = null;
    subscriptionRunIdRef.current = null;
    snapshotVersionRef.current = null;
    setRunSnapshot(null);
    setRunContext(null);
    setLatestRunEvent(null);
    setPendingConfirmation(null);
    setConfirmationText("");
  }, []);

  useEffect(() => () => subscriptionRef.current?.(), []);

  const refreshRun = useCallback(async (runId: string, conversationId = getConversationProjection().conversationId, generation = getConversationProjection().generation): Promise<boolean> => {
    const [snapshot, contextResponse] = await Promise.all([getRunSnapshot(runId), getRunContext(runId)]);
    if (conversationId === null || snapshot.run.conversation_id !== conversationId || !isCurrentProjection(conversationId, generation)) return false;
    const previous = snapshotVersionRef.current;
    if (previous?.runId === runId && previous.generation === generation && previous.version > snapshot.run.version) return true;
    snapshotVersionRef.current = { runId, generation, version: snapshot.run.version };
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

  const activeRunId = isWorkflowExecutionActive(runSnapshot) ? runSnapshot!.run.run_id : null;
  useEffect(() => {
    if (!activeRunId) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const reconcile = async (): Promise<void> => {
      try {
        await refreshRun(activeRunId);
      } catch {
        if (!disposed) onStatusLine("실행 상태를 확인하지 못했습니다. 자동으로 다시 확인합니다.");
      } finally {
        if (!disposed) timer = setTimeout(() => void reconcile(), 3000);
      }
    };
    timer = setTimeout(() => void reconcile(), 3000);
    return () => { disposed = true; clearTimeout(timer); };
  }, [activeRunId, onStatusLine, refreshRun]);

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
      onEvent: (event) => {
        setLatestRunEvent(event);
        void refreshRun(runId, conversationId, generation);
      },
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

  const handleResumeAfterReauth = useCallback(async (): Promise<void> => {
    if (!runSnapshot || runSnapshot.run.status !== "REAUTH_REQUIRED" || busyCommand) return;
    const operation = `reauth-completed:${runSnapshot.run.run_id}`;
    setBusyCommand(operation);
    try {
      await resumeRun({
        run_id: runSnapshot.run.run_id,
        command_id: commandIdFor(operation),
        expected_version: runSnapshot.run.version,
        resume_kind: "REAUTH_COMPLETED",
      });
      completeCommand(operation);
      await selectRun(runSnapshot.run.run_id);
    } catch (error) {
      await refreshRun(runSnapshot.run.run_id);
      throw error;
    } finally {
      setBusyCommand(null);
    }
  }, [busyCommand, commandIdFor, completeCommand, refreshRun, runSnapshot, selectRun, setBusyCommand]);

  const handleAdjustContext = useCallback(async (
    adjustmentKind: "EXCLUDE_EVIDENCE" | "RETRIEVE_MORE",
    value: string[] | string,
  ): Promise<void> => {
    const preview = runSnapshot?.context_preview;
    if (!runSnapshot || !preview?.adjustment_allowed || busyCommand) return;
    if (!preview.allowed_adjustments.includes(adjustmentKind)) return;
    const operation = `adjust-context:${runSnapshot.run.run_id}:${preview.retrieval_revision}:${adjustmentKind}`;
    setBusyCommand(operation);
    try {
      await adjustRunContext({
        run_id: runSnapshot.run.run_id,
        command_id: commandIdFor(operation),
        expected_version: runSnapshot.run.version,
        expected_retrieval_revision: preview.retrieval_revision,
        adjustment_kind: adjustmentKind,
        segment_ids: adjustmentKind === "EXCLUDE_EVIDENCE" ? value as string[] : null,
        requested_information: adjustmentKind === "RETRIEVE_MORE" ? value as string : null,
      });
      completeCommand(operation);
      await selectRun(runSnapshot.run.run_id);
    } catch (error) {
      await refreshRun(runSnapshot.run.run_id);
      throw error;
    } finally {
      setBusyCommand(null);
    }
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

  return { runSnapshot, runContext, latestRunEvent, pendingConfirmation, confirmationText, setConfirmationText, resetRunProjection, refreshRun, selectRun, selectConversation, handleCancelRun, handleResumeRun, handleResumeAfterReauth, handleAdjustContext, handleConfirmation };
}
