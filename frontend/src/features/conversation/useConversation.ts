import { useCallback, useRef, useState } from "react";
import type { CurrentGoogleAccount } from "../settings";
import { useActionPlanCommands } from "../approval";
import { useRecoveryCommands } from "../recovery";
import { useRequestComposerController, useRunProjection, useStableCommandIds } from "../run";
import { createConversation } from "./api/create_conversation";
import { useConversationHistoryProjection } from "./conversation_history_panel";

export type { PendingConfirmation } from "../run";

type UseConversationOptions = {
  currentAccount: CurrentGoogleAccount["account"];
  selectedResourceHandles: string[];
  onStatusLine: (message: string) => void;
};

export function useConversation({ currentAccount, selectedResourceHandles, onStatusLine }: UseConversationOptions) {
  const [busyCommand, setBusyCommand] = useState<string | null>(null);
  const resetRunProjectionRef = useRef<() => void>(() => undefined);
  const onResetProjection = useCallback(() => resetRunProjectionRef.current(), []);
  const history = useConversationHistoryProjection({ onStatusLine, onResetProjection });
  const { commandIdFor, completeCommand } = useStableCommandIds();
  const run = useRunProjection({
    busyCommand,
    setBusyCommand,
    commandIdFor,
    completeCommand,
    beginConversationProjection: history.beginConversationProjection,
    getConversationProjection: history.getConversationProjection,
    isCurrentProjection: history.isCurrentProjection,
    reloadConversationHistory: history.reloadConversationHistory,
    selectConversationHistory: history.selectConversation,
    isRunHistorySynced: history.isRunHistorySynced,
    markRunHistorySynced: history.markRunHistorySynced,
    onStatusLine,
  });
  resetRunProjectionRef.current = run.resetRunProjection;

  const composer = useRequestComposerController({
    currentAccountId: currentAccount?.account_id ?? null,
    selectedConversationId: history.selectedConversationId,
    selectedResourceHandles,
    busyCommand,
    setBusyCommand,
    getProjectionGeneration: () => history.getConversationProjection().generation,
    beginConversationProjection: history.beginConversationProjection,
    reloadConversationHistory: history.reloadConversationHistory,
    refreshConversations: history.refreshConversations,
    selectRun: run.selectRun,
    onStatusLine,
    commandIdFor,
    completeCommand,
    createConversation,
  });
  const actionCommands = useActionPlanCommands({
    runSnapshot: run.runSnapshot,
    currentAccountId: currentAccount?.account_id ?? null,
    busyCommand,
    setBusyCommand,
    commandIdFor,
    completeCommand,
    selectRun: run.selectRun,
    refreshRun: run.refreshRun,
  });
  const recoveryCommands = useRecoveryCommands({
    runSnapshot: run.runSnapshot,
    busyCommand,
    setBusyCommand,
    commandIdFor,
    completeCommand,
    refreshRun: run.refreshRun,
  });

  return {
    conversations: history.conversations,
    selectedConversationId: history.selectedConversationId,
    historyMessages: history.historyMessages,
    runSnapshot: run.runSnapshot,
    runContext: run.runContext,
    composerText: composer.composerText,
    composerError: composer.composerError,
    busyCommand,
    pendingConfirmation: run.pendingConfirmation,
    confirmationText: run.confirmationText,
    setComposerText: composer.setComposerText,
    setComposerError: composer.setComposerError,
    setConfirmationText: run.setConfirmationText,
    refreshConversations: history.refreshConversations,
    beginConversationProjection: history.beginConversationProjection,
    selectConversation: run.selectConversation,
    selectRun: run.selectRun,
    refreshRun: run.refreshRun,
    handleStartRun: composer.handleStartRun,
    ...actionCommands,
    handleCancelRun: run.handleCancelRun,
    handleResumeRun: run.handleResumeRun,
    handleConfirmation: run.handleConfirmation,
    ...recoveryCommands,
  };
}
