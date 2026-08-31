import { useCallback } from "react";
import type { RunAction, RunSnapshot } from "../../api/contract";
import type { StagedAttachmentDescriptor } from "../attachment/api/stage_attachment";
import { approveAction, modifyAction, prepareRetry, rejectAction } from "./api/action_commands";

type Options = { runSnapshot: RunSnapshot | null; currentAccountId: string | null; busyCommand: string | null; setBusyCommand: (value: string | null) => void; commandIdFor: (operation: string) => string; completeCommand: (operation: string) => void; selectRun: (runId: string) => Promise<void>; refreshRun: (runId: string) => Promise<boolean> };

export function useActionPlanCommands({ runSnapshot, currentAccountId, busyCommand, setBusyCommand, commandIdFor, completeCommand, selectRun, refreshRun }: Options) {
  const handleApprove = useCallback(async (action: RunAction, acknowledgements: ReadonlySet<string> = new Set()): Promise<void> => {
    if (!runSnapshot || !currentAccountId || busyCommand) return;
    const operation = `approve-${action.action_id}`;
    setBusyCommand(operation);
    try {
      await approveAction({ action_id: action.action_id, command_id: commandIdFor(operation), expected_version: action.version, duplicate_acknowledged: acknowledgements.has("TASK_DUPLICATE"), calendar_conflict_acknowledged: acknowledgements.has("CALENDAR_CONFLICT") });
      completeCommand(operation);
      await selectRun(runSnapshot.run.run_id);
    } catch (error) { await refreshRun(runSnapshot.run.run_id); throw error; }
    finally { setBusyCommand(null); }
  }, [busyCommand, commandIdFor, completeCommand, currentAccountId, refreshRun, runSnapshot, selectRun, setBusyCommand]);

  const handleSimpleAction = useCallback(async (kind: "modify" | "reject" | "retry", action: RunAction, argumentsPatch: Record<string, unknown> = {}): Promise<void> => {
    if (!runSnapshot || busyCommand) return;
    const operation = `${kind}-${action.action_id}`;
    setBusyCommand(operation);
    try {
      const commandId = commandIdFor(operation);
      if (kind === "modify") await modifyAction({ action_id: action.action_id, command_id: commandId, expected_version: action.version, arguments_patch: argumentsPatch });
      else if (kind === "reject") await rejectAction({ action_id: action.action_id, command_id: commandId, expected_version: action.version });
      else await prepareRetry({ action_id: action.action_id, command_id: commandId, expected_version: action.version });
      completeCommand(operation);
      await selectRun(runSnapshot.run.run_id);
    } catch (error) { await refreshRun(runSnapshot.run.run_id); throw error; }
    finally { setBusyCommand(null); }
  }, [busyCommand, commandIdFor, completeCommand, refreshRun, runSnapshot, selectRun, setBusyCommand]);

  const handleAttachDescriptors = useCallback(async (action: RunAction, descriptors: StagedAttachmentDescriptor[]): Promise<void> => {
    if (!runSnapshot || busyCommand || descriptors.length === 0) return;
    const operation = `attachment-modify-${action.action_id}`;
    setBusyCommand(`modify-${action.action_id}`);
    try {
      await modifyAction({ action_id: action.action_id, command_id: commandIdFor(operation), expected_version: action.version, arguments_patch: { attachments: descriptors } });
      completeCommand(operation);
      await selectRun(runSnapshot.run.run_id);
    } catch (error) { await refreshRun(runSnapshot.run.run_id); throw error; }
    finally { setBusyCommand(null); }
  }, [busyCommand, commandIdFor, completeCommand, refreshRun, runSnapshot, selectRun, setBusyCommand]);

  return { handleApprove, handleSimpleAction, handleAttachDescriptors };
}
